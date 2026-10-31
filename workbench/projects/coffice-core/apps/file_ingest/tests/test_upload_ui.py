import unittest
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


class UploadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.css = (STATIC / "ingest.css").read_text(encoding="utf-8")
        cls.javascript = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_upload_page_has_only_file_picker_and_row_parameters(self):
        self.assertNotIn("mode-tabs", self.html)
        self.assertNotIn("parameterForm", self.html)
        for field in ("平台", "公司", "店铺", "报表名称", "识别状态", "操作"):
            self.assertIn(f"<th>{field}</th>", self.html)
        self.assertIn('id="selectAllFiles"', self.html)
        self.assertIn('id="selectedFileSummary"', self.html)

    def test_unsubmitted_files_are_restored_after_page_navigation(self):
        for marker in (
            "indexedDB.open(PENDING_UPLOAD_DB_NAME, PENDING_UPLOAD_DB_VERSION)",
            "createObjectStore(PENDING_UPLOAD_STORE",
            "function persistPendingFile(item)",
            "function restorePendingFile(record)",
            "async function restorePendingFiles()",
            "void deletePendingFile(id)",
            "await restorePendingFiles();",
        ):
            self.assertIn(marker, self.javascript)
        self.assertIn("item.file", self.javascript)
        self.assertIn("selected: state.selectedFiles.has(item.id)", self.javascript)
        self.assertIn("未提交文件会保留在当前浏览器中", self.html)

    def test_row_dropdown_and_submit_behaviors_are_present(self):
        self.assertIn("cellDropdownSearch", self.javascript)
        self.assertIn("selectedFiles", self.javascript)
        self.assertIn("data-submit-one", self.javascript)
        self.assertIn("XMLHttpRequest", self.javascript)
        self.assertIn("X-CSRF-Token", self.javascript)
        self.assertIn("/api/ingest/runs/${runId}/fail", self.javascript)
        self.assertIn("data-complete-run", self.javascript)
        self.assertIn("data-delete-run", self.javascript)
        self.assertIn("/api/ingest/guess?filename=", self.javascript)

    def test_upload_states_and_ellipsis_styles_are_present(self):
        for selector in (".upload-file-item.uploading", ".upload-file-item.uploaded", ".cell-dropdown-search"):
            self.assertIn(selector, self.css)
        self.assertIn("text-overflow: ellipsis", self.css)
        self.assertIn("opacity: 1", self.css)

    def test_successful_files_fade_out_and_failed_errors_are_collapsible(self):
        self.assertIn("AUTO_REMOVE_FILE_STATUSES", self.javascript)
        self.assertIn("scheduleSuccessfulFileRemoval", self.javascript)
        self.assertIn("data-error-toggle", self.javascript)
        self.assertIn("data-copy-message", self.javascript)
        self.assertIn(".upload-file-item.is-removing", self.css)
        self.assertIn(".file-row-removing", self.css)
        self.assertIn(".row-error-content", self.css)
        self.assertIn(".copy-error-button", self.css)
        self.assertIn("商品\\s*编码\\s*未配置", self.javascript)
        self.assertIn("copyWithSelection", self.javascript)
        self.assertIn("const fallbackCopied=copyWithSelection(text)", self.javascript)
        self.assertIn("event.clipboardData.setData('text/plain',text)", self.javascript)
        self.assertIn("document.addEventListener('copy',handleCopy,true)", self.javascript)
        self.assertIn("clipboardReadback", self.javascript)
        self.assertIn("navigator.clipboard?.readText", self.javascript)
        self.assertIn("if (fallbackCopied && verified!==false)return;", self.javascript)
        self.assertIn('<tr class="upload-error-row"', self.javascript)
        self.assertIn("const errorDisclosure=renderErrorDisclosure(item),recognitionHtml=", self.javascript)
        self.assertIn("block.hidden=expanded", self.javascript)
        self.assertIn("recognition-error-toggle", self.javascript)

    def test_detail_copy_toast_matches_upload_toast_surface(self):
        self.assertIn("body .app-global-toast", self.css)
        self.assertIn("padding: 9px 16px", self.css)
        self.assertIn("border-radius: 4px", self.css)
        self.assertIn("font-size: 14px", self.css)
        self.assertIn("line-height: normal", self.css)
        self.assertIn("text-align: start", self.css)
        self.assertIn("body .app-global-toast.success { background: #237804; }", self.css)
        self.assertIn("body .app-global-toast.error { background: #b42318; }", self.css)

    def test_upload_failure_disclosure_is_outside_filename_cell(self):
        render_start = self.javascript.index("function renderFiles")
        render_end = self.javascript.index("function removeFile", render_start)
        render_source = self.javascript[render_start:render_end]
        self.assertIn("<div class=\"file-name-cell\"", render_source)
        self.assertNotIn("file-name-cell\" title=\"${esc(item.file.name)}\">${esc(item.file.name)}</div>${renderErrorDisclosure(item)}", render_source)
        self.assertIn("colspan=\"8\"", render_source)
        self.assertIn(".upload-data-table .recognition-col { width: 170px; }", self.css)
        self.assertIn(".upload-data-table .upload-error-row > td", self.css)

    def test_error_copy_actions_are_only_in_detail_tables(self):
        run_list_start = self.javascript.index("async function loadRuns")
        run_list_end = self.javascript.index("function renderRunPagination", run_list_start)
        etl_list_start = self.javascript.index("async function loadEtls")
        etl_list_end = self.javascript.index("function renderEtlPagination", etl_list_start)

        self.assertNotIn("data-copy-message", self.javascript[run_list_start:run_list_end])
        self.assertNotIn("data-copy-message", self.javascript[etl_list_start:etl_list_end])
        self.assertIn("file-detail:", self.javascript)
        self.assertIn("etl-task:", self.javascript)
        self.assertIn("function detailMessage", self.javascript)
        self.assertIn("复制警告信息", self.javascript)
        self.assertIn("detailCopyMessageButton", self.javascript)
        self.assertIn('data-copy-kind="${tone===\'warning\'?\'warning\':\'error\'}"', self.javascript)
        self.assertIn("copy.dataset.copyKind==='warning'?'警告信息已复制':'错误信息已复制'", self.javascript)
        self.assertIn("$('ingestFileDetailBody').onclick", self.javascript)
        self.assertIn("$('etlTaskBody').onclick", self.javascript)
        self.assertIn(".file-detail-operation-col { width: 185px;", self.css)
        self.assertIn(".etl-task-table td:last-child { width: 170px; min-width: 170px; }", self.css)
        self.assertIn("class=\"text-button detail-action\" data-retry-etl-task=", self.javascript)
        self.assertIn("class=\"text-button detail-action\" data-retry-ingest-file=", self.javascript)
        self.assertIn("i-refresh", self.javascript)

    def test_operation_log_filters_reuse_date_range_control(self):
        self.assertIn('data-date-range="logDateFrom,logDateTo"', self.html)
        self.assertIn('id="logType"', self.html)
        self.assertIn('id="logOperator"', self.html)
        self.assertIn('id="logKeyword"', self.html)
        self.assertIn("operation_type", self.javascript)
        self.assertIn("dateRangeDropdown", self.javascript)
        self.assertIn("renderLogFilterOptions", self.javascript)

    def test_grouped_navigation_and_platform_fee_pages_are_present(self):
        self.assertIn('data-nav-group="ingest"', self.html)
        self.assertIn('data-nav-group="platform-fees"', self.html)
        for page, query_id, reset_id in (
            ("feeCategories", "searchCategories", "resetCategories"),
            ("feeMappings", "searchFees", "resetFees"),
            ("rawFees", "searchRawFees", "resetRawFees"),
        ):
            self.assertIn(f'data-page="{page}"', self.html)
            self.assertIn(f'id="{page}Page"', self.html)
        self.assertNotIn('data-page="fees"', self.html)

    def test_etl_detail_and_category_management_behaviors_are_present(self):
        self.assertIn('id="etlDetailDialog"', self.html)
        self.assertIn("showEtlDetail", self.javascript)
        self.assertIn("data-retry-etl-task", self.javascript)
        self.assertIn('id="categoryDialog"', self.html)
        self.assertIn("saveCategory", self.javascript)

    def test_fee_mapping_dialog_reuses_the_inline_category_dropdown(self):
        self.assertIn('id="feeMappingCategoryTrigger"', self.html)
        self.assertIn('id="feeMappingCategoryCode"', self.html)
        self.assertNotIn('id="feeMappingCategoryNames"', self.html)
        self.assertIn("trigger.id==='feeMappingCategoryTrigger'", self.javascript)
        self.assertIn("$('feeMappingDialog').addEventListener('close',closeAssignDropdown)", self.javascript)

    def test_fee_mapping_dropdown_is_moved_into_modal_top_layer(self):
        self.assertIn("dialog.appendChild(drop)", self.javascript)
        self.assertIn("drop.classList.add('fee-dialog-dropdown')", self.javascript)
        self.assertIn("if(home&&drop.parentElement!==home)home.appendChild(drop)", self.javascript)
        self.assertIn(".assign-dropdown.fee-dialog-dropdown", self.css)

    def test_fee_mapping_dropdown_search_names_the_category_management_field(self):
        self.assertIn('id="assignSearch" placeholder="查找一级分类管理名称"', self.html)
        self.assertNotIn("查找或创建选项", self.html)

    def test_fee_mapping_category_trigger_matches_form_control_dimensions(self):
        self.assertIn(".fee-modal-category .assign-trigger { height: 32px;", self.css)
        self.assertIn("padding: 0 12px 0 10px; font-size: 13px;", self.css)
        self.assertIn(".fee-modal-category .assign-trigger svg { width: 12px; height: 12px;", self.css)

    def test_fee_category_management_uses_platform_filter_and_generated_code(self):
        self.assertIn('id="categoryPlatform"', self.html)
        self.assertIn('<th>排序</th><th>分类编码</th>', self.html)
        self.assertIn('id="categoryFormPlatform"', self.html)
        self.assertNotIn('id="categoryFormCode"', self.html)
        self.assertIn("closest('label')", self.javascript)
        self.assertIn("platformField.hidden=Boolean(item)", self.javascript)
        self.assertIn("platform_code", self.javascript)
        self.assertIn("categoryFormPlatform", self.javascript)

    def test_category_view_filters_fee_mappings_by_category_name(self):
        self.assertIn("$('feeKeyword').value=item.primary_category_name", self.javascript)
        service = (STATIC.parent / "service.py").read_text(encoding="utf-8")
        self.assertIn('"primary_category_code", "primary_category_name", "platform_name"', service)

    def test_fee_mapping_filters_can_be_reset(self):
        self.assertIn('id="resetFees"', self.html)
        self.assertIn("$('resetFees').onclick", self.javascript)
        reset = next(line for line in self.javascript.splitlines() if "$('resetFees').onclick" in line)
        for field in ('feePlatform', 'feeDocument', 'feeStatus', 'feeTreatment', 'feeKeyword'):
            self.assertIn(f"$('{field}').value=''", reset)

    def test_platform_fee_toolbars_match_bank_account_layout(self):
        for page, query_id, reset_id in (
            ("feeCategories", "searchCategories", "resetCategories"),
            ("feeMappings", "searchFees", "resetFees"),
            ("rawFees", "searchRawFees", "resetRawFees"),
        ):
            start = self.html.index(f'<section class="page" id="{page}Page">')
            end = self.html.index("</section>", start)
            section = self.html[start:end]
            self.assertIn('class="toolbar fee-page-toolbar"', section)
            self.assertNotIn("fee-page-header", section)
            self.assertIn('class="toolbar-group actions"', section)
            self.assertLess(section.index('class="search-field"'), section.index(f'id="{query_id}"'))
            self.assertLess(section.index(f'id="{query_id}"'), section.index(f'id="{reset_id}"'))
        self.assertIn('id="addCategory"', self.html)
        self.assertIn('id="exportFees"', self.html)
        self.assertIn('id="batchMapFees"', self.html)
        self.assertIn('class="button primary batch-toggle-button" id="batchMapFees"', self.html)
        self.assertIn('href="#i-check-square"', self.html)
        self.assertIn('id="batchMapFeesLabel">开启批量勾选', self.html)
        self.assertIn('id="exportRawFees"', self.html)
        self.assertNotIn('id="selectionBar"', self.html)
        self.assertNotIn('id="feeBatchMappingDialog"', self.html)
        self.assertIn('id="feeMappingTable"', self.html)
        self.assertIn("feeBatchMode", self.javascript)
        self.assertIn("toggleFeeBatchMode", self.javascript)
        self.assertNotIn("openFeeBatchMappingDialog", self.javascript)
        self.assertNotIn("saveFeeBatchMapping", self.javascript)
        self.assertIn("showTablePopover('batch-confirm'", self.javascript)
        self.assertIn("#i-x-square", self.javascript)
        self.assertIn("关闭批量勾选", self.javascript)
        self.assertIn("batch-mode-active", self.javascript)
        self.assertIn(".button.batch-toggle-button.batch-mode-active", self.css)
        self.assertIn("margin-bottom: 16px", self.css)

    def test_ingest_detail_table_keeps_long_file_names_inside_file_column(self):
        self.assertIn('class="data-table ingest-file-detail-table"', self.html)
        self.assertIn('class="file-detail-file-col"', self.html)
        self.assertIn("table-layout: fixed", self.css)
        self.assertIn(".ingest-file-detail-table th", self.css)
        self.assertIn(".ingest-file-detail-table .status-tag", self.css)
        self.assertIn("white-space: normal", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)

    def test_detail_actions_open_immediately_and_ignore_stale_requests(self):
        self.assertIn('data-run-detail="${esc(r.run_id)}"', self.javascript)
        self.assertIn("DETAIL_DIALOG_IDS=['ingestDetailDialog','etlDetailDialog']", self.javascript)
        self.assertIn("hasOdsBatchMetrics", self.javascript)
        self.assertIn("ODS已写入 · 统计稍后可用", self.javascript)
        self.assertIn("state.detailRequestController?.abort()", self.javascript)
        self.assertIn("if(!isCurrentDetailRequest(request))return;", self.javascript)
        self.assertIn("closeDetailDialog(button.dataset.closeDialog)", self.javascript)
        for function_name, dialog_id in (("showRunDetail", "ingestDetailDialog"), ("showEtlDetail", "etlDetailDialog")):
            function_start = self.javascript.index(f"async function {function_name}")
            request_start = self.javascript.index(f"beginDetailRequest('{dialog_id}')", function_start)
            api_start = self.javascript.index("await api(", request_start)
            self.assertLess(request_start, api_start)
        self.assertNotIn("$('ingestDetailDialog').showModal();", self.javascript)
        self.assertNotIn("$('etlDetailDialog').showModal();", self.javascript)


if __name__ == "__main__":
    unittest.main()
