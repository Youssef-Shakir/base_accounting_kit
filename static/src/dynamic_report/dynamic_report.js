/** @odoo-module **/
/* DoniaLink Accounting - interactive financial reports: P&L, balance sheet, trial balance,
 * general ledger, partner ledger, aged partner balance.
 * Based on the Odoo 18 Full Accounting Kit by Cybrosys Technologies (LGPL v3). */
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { download } from "@web/core/network/download";
import { formatMonetary } from "@web/views/fields/formatters";
import { _t } from "@web/core/l10n/translation";

const LAZY_REPORTS = ["general_ledger", "partner_ledger", "aged_balance"];
const AS_OF_REPORTS = ["balance_sheet", "aged_balance"];
const PERIOD_ONLY_REPORTS = ["trial_balance", "general_ledger", "partner_ledger"];
const COMPARABLE_REPORTS = ["profit_and_loss", "balance_sheet"];

function parseSet(text) {
    return new Set(text ? text.split(",") : []);
}

export class DynamicReport extends Component {
    static template = "base_accounting_kit.DynamicReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.ui = useService("ui");
        this.reportKey = this.props.action.params?.report_key || "profit_and_loss";
        // the action state is kept in the URL, so it is stored as text
        const saved = this.props.state || {};
        let options = {};
        try {
            options = saved.dl_options ? JSON.parse(saved.dl_options) : {};
        } catch {
            options = {};
        }
        delete options.unfold_all;
        this.state = useState({
            report: null,
            options,
            folded: parseSet(saved.dl_folded), // sections closed by the user
            unfolded: parseSet(saved.dl_unfolded), // lazy sections opened by the user
            loading: false,
            search: options.search || "",
        });
        this.loaded = new Set(); // lazy sections whose children are loaded
        this.dateFilters = [
            ["today", _t("Today")],
            ["this_month", _t("This month")],
            ["last_month", _t("Last month")],
            ["this_quarter", _t("This quarter")],
            ["last_quarter", _t("Last quarter")],
            ["this_year", _t("This financial year")],
            ["last_year", _t("Last financial year")],
            ["custom", _t("Custom")],
        ];
        useSetupAction({ getLocalState: () => this.localState() });
        onWillStart(async () => {
            await this.load();
            await this.restoreUnfolded();
        });
    }

    // ---------- report kinds ----------

    get isLazy() {
        return LAZY_REPORTS.includes(this.reportKey);
    }
    get isAsOf() {
        return AS_OF_REPORTS.includes(this.reportKey);
    }
    get canCompare() {
        return COMPARABLE_REPORTS.includes(this.reportKey);
    }
    get hasPartnerType() {
        return ["partner_ledger", "aged_balance"].includes(this.reportKey);
    }
    get partnerTypes() {
        const types = [
            ["receivable", _t("Receivable")],
            ["payable", _t("Payable")],
        ];
        return this.reportKey === "partner_ledger"
            ? [["both", _t("Receivable and Payable")], ...types]
            : types;
    }
    get filters() {
        return this.dateFilters.filter(
            ([key]) => !(PERIOD_ONLY_REPORTS.includes(this.reportKey) && key === "today")
        );
    }

    // ---------- state ----------

    localState() {
        return {
            dl_options: JSON.stringify({ ...this.state.options, unfold_all: false }),
            dl_folded: [...this.state.folded].join(","),
            dl_unfolded: [...this.state.unfolded].join(","),
        };
    }
    saveState() {
        this.props.updateActionState?.(this.localState());
    }

    async load(changes = {}) {
        this.state.loading = true;
        try {
            const report = await this.orm.call("account.dynamic.report", "get_report", [
                this.reportKey,
                { ...this.state.options, ...changes },
            ]);
            this.loaded = new Set();
            if (report.options.unfold_all) {
                for (const line of report.lines) {
                    if (line.lazy) {
                        this.loaded.add(line.id);
                    }
                }
            }
            this.state.report = report;
            this.state.options = report.options;
            this.saveState();
        } finally {
            this.state.loading = false;
        }
    }

    async restoreUnfolded() {
        for (const id of [...this.state.unfolded]) {
            const line = this.lineById[id];
            if (!line) {
                this.state.unfolded.delete(id);
            } else if (line.lazy && !this.loaded.has(id)) {
                await this.loadChildren(line);
            }
        }
    }

    // ---------- filters ----------

    onDateFilter(ev) {
        const value = ev.target.value;
        if (value === "custom") {
            this.state.options = { ...this.state.options, date_filter: "custom" };
            return;
        }
        this.reload({ date_filter: value });
    }
    onCustomDate(field, ev) {
        this.reload({ date_filter: "custom", [field]: ev.target.value || false });
    }
    onOption(field, ev) {
        const value = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        this.reload({ [field]: value });
    }
    onSearch(ev) {
        if (ev.type === "change" || ev.key === "Enter") {
            this.reload({ search: this.state.search });
        }
    }
    async reload(changes) {
        // new filters give new lines: lazy sections are closed again
        this.state.unfolded = new Set();
        await this.load({ ...changes, unfold_all: false });
    }

    // ---------- lines ----------

    get lineById() {
        const map = {};
        for (const line of this.state.report?.lines || []) {
            map[line.id] = line;
        }
        return map;
    }
    isOpen(line) {
        if (!line) {
            return true;
        }
        return line.lazy ? this.state.unfolded.has(line.id) : !this.state.folded.has(line.id);
    }
    get visibleLines() {
        const byId = this.lineById;
        return (this.state.report?.lines || []).filter((line) =>
            line.ancestors.every((id) => this.isOpen(byId[id]))
        );
    }
    async loadChildren(line) {
        const children = await this.orm.call("account.dynamic.report", "get_children", [
            this.reportKey,
            this.state.options,
            line.id,
        ]);
        const lines = this.state.report.lines;
        const index = lines.findIndex((l) => l.id === line.id);
        lines.splice(index + 1, 0, ...children);
        this.loaded.add(line.id);
    }
    async toggle(line) {
        if (!line.foldable) {
            return;
        }
        if (line.lazy) {
            if (this.state.unfolded.has(line.id)) {
                this.state.unfolded.delete(line.id);
            } else {
                if (!this.loaded.has(line.id)) {
                    await this.loadChildren(line);
                }
                this.state.unfolded.add(line.id);
            }
        } else if (this.state.folded.has(line.id)) {
            this.state.folded.delete(line.id);
        } else {
            this.state.folded.add(line.id);
        }
        this.saveState();
    }
    async foldAll(fold) {
        if (this.isLazy) {
            if (fold) {
                this.state.unfolded = new Set();
            } else {
                await this.load({ unfold_all: true });
                this.state.unfolded = new Set(this.loaded);
            }
        } else {
            this.state.folded = new Set(
                fold ? this.state.report.lines.filter((l) => l.foldable && l.level > 0).map((l) => l.id) : []
            );
        }
        this.saveState();
    }
    isClickable(line) {
        return ["account", "item", "more"].includes(line.kind);
    }
    async openLine(line) {
        let action;
        if (line.kind === "account") {
            action = await this.orm.call("account.dynamic.report", "action_open_journal_items", [
                this.reportKey,
                this.state.options,
                line.account_id,
            ]);
        } else {
            action = await this.orm.call("account.dynamic.report", "action_open_line", [
                this.reportKey,
                this.state.options,
                {
                    kind: line.kind,
                    move_id: line.move_id || false,
                    account_id: line.account_id || false,
                    partner_id: line.partner_id ?? false,
                },
            ]);
        }
        if (action) {
            this.action.doAction(action);
        }
    }

    // ---------- formatting ----------

    isNumeric(column) {
        return (column.type || "monetary") !== "text";
    }
    isPercent(column) {
        return column.percent || column.type === "percent";
    }
    format(value, column) {
        if (value === null || value === undefined || value === "") {
            return "";
        }
        if (column.type === "text") {
            return value;
        }
        if (this.isPercent(column)) {
            return `${value.toLocaleString()} %`;
        }
        return formatMonetary(value, { currencyId: this.state.report.currency_id });
    }
    isNegative(value, column) {
        return this.isNumeric(column) && !this.isPercent(column) && value < 0;
    }

    // ---------- export ----------

    async printPdf() {
        const action = await this.orm.call("account.dynamic.report", "action_print_pdf", [
            this.reportKey,
            this.state.options,
        ]);
        this.action.doAction(action);
    }
    async exportXlsx() {
        this.ui.block();
        try {
            await download({
                url: "/donialink_accounting/report/xlsx",
                data: { report_key: this.reportKey, options: JSON.stringify(this.state.options) },
            });
        } finally {
            this.ui.unblock();
        }
    }
}

registry.category("actions").add("donialink_accounting_report", DynamicReport);
