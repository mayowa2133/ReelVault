from __future__ import annotations

from datetime import datetime, timezone
import re

from googleapiclient.discovery import build

from app.config import Settings
from app.models.schemas import ContentPillar, ProcessingStatus, SHEET_COLUMNS, SheetRow, utc_now_iso
from app.services.google_drive_service import extract_drive_folder_id_from_link
from app.services.google_oauth_service import GOOGLE_SHEETS_SCOPE, GoogleOAuthCredentialsProvider
from app.utils.errors import ExternalServiceError


class GoogleSheetsService:
    """Append and update ReelVault rows in Google Sheets."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.credentials_provider = GoogleOAuthCredentialsProvider(settings, scopes=[GOOGLE_SHEETS_SCOPE])
        self._service = None

    @property
    def sheet_url(self) -> str | None:
        return self.settings.google_sheet_url

    def append_row(self, row: SheetRow) -> int:
        self.ensure_headers()
        row_index = self.next_row_index()
        self._update_row(row_index, row)
        self.ensure_used_checkbox_column(start_row=row_index, end_row=row_index)
        return row_index

    def update_row(self, row_index: int, row: SheetRow) -> None:
        self._update_row(row_index, row)

    def sync_used_value(
        self,
        *,
        used: bool,
        pillar: str,
        inspiration_folder_link: str = "",
        shortcode: str = "",
        reel_url: str = "",
        edited_tab_name: str = "",
        edited_row_number: int | None = None,
        used_at: str = "",
    ) -> int:
        used_at = (used_at or utc_now_iso()) if used else ""
        tabs = unique_tab_names([self._tab_name(), pillar_tab_name(pillar) if pillar else ""])
        rows_by_tab: dict[str, list[tuple[int, SheetRow]]] = {}
        for tab_name in tabs:
            if not self.tab_exists(tab_name):
                continue
            rows_by_tab[tab_name] = self.iter_rows(tab_name)

        updates = used_sync_updates(
            rows_by_tab,
            used=used,
            inspiration_folder_link=inspiration_folder_link,
            shortcode=shortcode,
            reel_url=reel_url,
            edited_tab_name=edited_tab_name,
            edited_row_number=edited_row_number,
            used_at=used_at,
        )
        for tab_name, row_index in updates:
            self.update_used_state(tab_name, row_index, used, used_at=used_at)
        return len(updates)

    def iter_rows(self, tab_name: str | None = None) -> list[tuple[int, SheetRow]]:
        values = (
            self._values()
            .get(
                spreadsheetId=self._sheet_id(),
                range=f"{self._tab(tab_name)}!A2:{last_sheet_column()}",
            )
            .execute()
            .get("values", [])
        )
        rows: list[tuple[int, SheetRow]] = []
        for offset, values_row in enumerate(values, start=2):
            try:
                rows.append((offset, SheetRow.from_values(values_row)))
            except ValueError:
                continue
        return rows

    def update_used_state(self, tab_name: str, row_index: int, used: bool, used_at: str = "") -> None:
        used_at = (used_at or utc_now_iso()) if used else ""
        used_column = column_letter(SHEET_COLUMNS.index("Used") + 1)
        used_at_column = column_letter(SHEET_COLUMNS.index("Used At") + 1)
        self._values().update(
            spreadsheetId=self._sheet_id(),
            range=f"{self._tab(tab_name)}!{used_column}{row_index}",
            valueInputOption="USER_ENTERED",
            body={"values": [["TRUE" if used else "FALSE"]]},
        ).execute()
        self._values().update(
            spreadsheetId=self._sheet_id(),
            range=f"{self._tab(tab_name)}!{used_at_column}{row_index}",
            valueInputOption="USER_ENTERED",
            body={"values": [[used_at]]},
        ).execute()

    def sort_tabs_for_usage(self, pillar: str = "") -> dict[str, bool]:
        tabs = unique_tab_names([self._tab_name(), pillar_tab_name(pillar) if pillar else ""])
        results: dict[str, bool] = {}
        for tab_name in tabs:
            if not self.tab_exists(tab_name):
                continue
            results[tab_name] = self.sort_tab_for_usage(tab_name)
        return results

    def sort_tab_for_usage(self, tab_name: str | None = None) -> bool:
        self.ensure_headers(tab_name)
        rows_with_indexes = self.iter_rows(tab_name)
        if len(rows_with_indexes) < 2:
            if rows_with_indexes:
                row_index = rows_with_indexes[0][0]
                self.ensure_used_checkbox_column(tab_name, start_row=row_index, end_row=row_index)
            return True

        if has_active_processing_rows([row for _row_index, row in rows_with_indexes]):
            return False

        sorted_rows = sort_rows_for_usage([row for _row_index, row in rows_with_indexes])
        start_row = 2
        end_row = start_row + len(sorted_rows) - 1
        self._values().update(
            spreadsheetId=self._sheet_id(),
            range=f"{self._tab(tab_name)}!A{start_row}:{last_sheet_column()}{end_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [row.to_values() for row in sorted_rows]},
        ).execute()
        self.ensure_used_checkbox_column(tab_name, start_row=start_row, end_row=end_row)
        return True

    def tab_exists(self, tab_name: str) -> bool:
        spreadsheet = (
            self._client()
            .spreadsheets()
            .get(spreadsheetId=self._sheet_id(), fields="sheets/properties/title")
            .execute()
        )
        return tab_name in {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}

    def _update_row(self, row_index: int, row: SheetRow, tab_name: str | None = None) -> None:
        if row_index <= 0:
            raise ExternalServiceError("Google Sheets row index must be positive", step="google_sheets")
        self.ensure_row_capacity(row_index, tab_name)
        self._values().update(
            spreadsheetId=self._sheet_id(),
            range=f"{self._tab(tab_name)}!A{row_index}:{last_sheet_column()}{row_index}",
            valueInputOption="USER_ENTERED",
            body={"values": [row.to_values()]},
        ).execute()

    def get_row(self, row_index: int) -> SheetRow:
        if row_index <= 0:
            raise ExternalServiceError("Google Sheets row index must be positive", step="google_sheets")
        values = (
            self._values()
            .get(
                spreadsheetId=self._sheet_id(),
                range=f"{self._tab()}!A{row_index}:{last_sheet_column()}{row_index}",
            )
            .execute()
            .get("values", [])
        )
        if not values:
            raise ExternalServiceError(f"Google Sheets row {row_index} was not found", step="google_sheets")
        return SheetRow.from_values(values[0])

    def append_pillar_row(self, row: SheetRow) -> int | None:
        if not row.pillar:
            return None
        tab_name = pillar_tab_name(row.pillar)
        self.ensure_headers(tab_name)
        row_index = self.next_row_index(tab_name)
        self._update_row(row_index, row, tab_name)
        self.ensure_used_checkbox_column(tab_name, start_row=row_index, end_row=row_index)
        return row_index

    def ensure_headers(self, tab_name: str | None = None) -> None:
        self.ensure_tab_exists(tab_name)
        existing = (
            self._values()
            .get(spreadsheetId=self._sheet_id(), range=f"{self._tab(tab_name)}!A1:{last_sheet_column()}1")
            .execute()
            .get("values", [])
        )
        existing_headers = existing[0] if existing else []
        if existing_headers == SHEET_COLUMNS:
            return
        headers = merge_headers(existing_headers, SHEET_COLUMNS)
        self._values().update(
            spreadsheetId=self._sheet_id(),
            range=f"{self._tab(tab_name)}!A1:{column_letter(len(headers))}1",
            valueInputOption="USER_ENTERED",
            body={"values": [headers]},
        ).execute()

    def ensure_all_pillar_tabs(self) -> None:
        for pillar in ContentPillar:
            self.ensure_headers(pillar_tab_name(pillar))

    def next_row_index(self, tab_name: str | None = None) -> int:
        return self.last_data_row(tab_name) + 1

    def last_data_row(self, tab_name: str | None = None) -> int:
        values = (
            self._values()
            .get(spreadsheetId=self._sheet_id(), range=f"{self._tab(tab_name)}!A:B")
            .execute()
            .get("values", [])
        )
        return last_data_row_from_key_values(values)

    def sync_used_checkbox_column(self, tab_name: str | None = None) -> None:
        last_row = self.last_data_row(tab_name)
        grid_row_count = self._sheet_grid_properties(tab_name)["rowCount"]
        if last_row >= 2:
            self.ensure_used_checkbox_column(tab_name, start_row=2, end_row=last_row)
        if last_row < grid_row_count:
            self.clear_used_checkbox_column(tab_name, start_row=last_row + 1, end_row=grid_row_count)

    def ensure_used_checkbox_column(
        self,
        tab_name: str | None = None,
        *,
        start_row: int = 2,
        end_row: int | None = None,
    ) -> None:
        if end_row is None:
            end_row = start_row
        if end_row < start_row:
            return
        sheet_id = self._sheet_gid(tab_name)
        used_column_index = SHEET_COLUMNS.index("Used")
        self._client().spreadsheets().batchUpdate(
            spreadsheetId=self._sheet_id(),
            body={
                "requests": [
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row - 1,
                                "endRowIndex": end_row,
                                "startColumnIndex": used_column_index,
                                "endColumnIndex": used_column_index + 1,
                            },
                            "rule": {
                                "condition": {"type": "BOOLEAN"},
                                "strict": True,
                                "showCustomUi": True,
                            },
                        }
                    }
                ]
            },
        ).execute()

    def clear_used_checkbox_column(self, tab_name: str | None = None, *, start_row: int, end_row: int) -> None:
        if end_row < start_row:
            return
        sheet_id = self._sheet_gid(tab_name)
        used_column_index = SHEET_COLUMNS.index("Used")
        self._client().spreadsheets().batchUpdate(
            spreadsheetId=self._sheet_id(),
            body={
                "requests": [
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row - 1,
                                "endRowIndex": end_row,
                                "startColumnIndex": used_column_index,
                                "endColumnIndex": used_column_index + 1,
                            }
                        }
                    }
                ]
            },
        ).execute()

        used_column = column_letter(used_column_index + 1)
        self._values().clear(
            spreadsheetId=self._sheet_id(),
            range=f"{self._tab(tab_name)}!{used_column}{start_row}:{last_sheet_column()}{end_row}",
        ).execute()

    def ensure_row_capacity(self, row_index: int, tab_name: str | None = None) -> None:
        grid_row_count = self._sheet_grid_properties(tab_name)["rowCount"]
        if row_index <= grid_row_count:
            return
        self._client().spreadsheets().batchUpdate(
            spreadsheetId=self._sheet_id(),
            body={
                "requests": [
                    {
                        "appendDimension": {
                            "sheetId": self._sheet_gid(tab_name),
                            "dimension": "ROWS",
                            "length": row_index - grid_row_count,
                        }
                    }
                ]
            },
        ).execute()

    def ensure_tab_exists(self, tab_name: str | None = None) -> None:
        spreadsheet = (
            self._client()
            .spreadsheets()
            .get(spreadsheetId=self._sheet_id(), fields="sheets/properties/title,sheets/properties/sheetId")
            .execute()
        )
        tab_name = self._tab_name(tab_name)
        existing_tabs = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
        if tab_name in existing_tabs:
            return

        self._client().spreadsheets().batchUpdate(
            spreadsheetId=self._sheet_id(),
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        ).execute()

    def _sheet_grid_properties(self, tab_name: str | None = None) -> dict[str, int]:
        spreadsheet = (
            self._client()
            .spreadsheets()
            .get(spreadsheetId=self._sheet_id(), fields="sheets/properties/title,sheets/properties/gridProperties")
            .execute()
        )
        wanted = self._tab_name(tab_name)
        for sheet in spreadsheet.get("sheets", []):
            properties = sheet["properties"]
            if properties["title"] == wanted:
                return properties["gridProperties"]
        raise ExternalServiceError(f"Google Sheets tab not found: {wanted}", step="google_sheets")

    def _values(self):
        return self._client().spreadsheets().values()

    def _client(self):
        if self._service is None:
            credentials = self.credentials_provider.get_credentials()
            self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return self._service

    def _sheet_id(self) -> str:
        if not self.settings.google_sheet_id:
            raise ExternalServiceError("GOOGLE_SHEET_ID is not configured", step="google_sheets")
        return self.settings.google_sheet_id

    def _tab(self, tab_name: str | None = None) -> str:
        escaped = self._tab_name(tab_name).replace("'", "''")
        return f"'{escaped}'"

    def _tab_name(self, tab_name: str | None = None) -> str:
        return tab_name or self.settings.google_sheet_tab_name or "Reels"

    def _sheet_gid(self, tab_name: str | None = None) -> int:
        spreadsheet = (
            self._client()
            .spreadsheets()
            .get(spreadsheetId=self._sheet_id(), fields="sheets/properties/title,sheets/properties/sheetId")
            .execute()
        )
        wanted = self._tab_name(tab_name)
        for sheet in spreadsheet.get("sheets", []):
            properties = sheet["properties"]
            if properties["title"] == wanted:
                return int(properties["sheetId"])
        raise ExternalServiceError(f"Google Sheets tab not found: {wanted}", step="google_sheets")


def parse_row_index(updated_range: str) -> int | None:
    match = re.search(r"![A-Z]+(\d+)(?::[A-Z]+\d+)?$", updated_range)
    if not match:
        return None
    return int(match.group(1))


def column_letter(index: int) -> str:
    if index <= 0:
        raise ValueError("Column index must be positive")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def last_sheet_column() -> str:
    return column_letter(len(SHEET_COLUMNS))


def merge_headers(existing_headers: list[str], required_headers: list[str]) -> list[str]:
    if not existing_headers:
        return required_headers
    merged = list(existing_headers)
    for header in required_headers:
        if header not in merged:
            merged.append(header)
    return merged


def last_data_row_from_key_values(values: list[list[str]]) -> int:
    last_row = 1
    for row_index, row in enumerate(values, start=1):
        if any(str(cell).strip() for cell in row[:2]):
            last_row = row_index
    return last_row


def pillar_tab_name(pillar: ContentPillar | str) -> str:
    value = pillar.value if isinstance(pillar, ContentPillar) else str(pillar)
    return value.strip() or "Unclassified"


def unique_tab_names(tab_names: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for tab_name in tab_names:
        tab_name = str(tab_name or "").strip()
        if not tab_name or tab_name in seen:
            continue
        seen.add(tab_name)
        unique.append(tab_name)
    return unique


def normalize_used_value(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() == "TRUE"


TERMINAL_SHEET_STATUSES = {
    ProcessingStatus.COMPLETE.value,
    ProcessingStatus.PARTIAL_COMPLETE.value,
    ProcessingStatus.INVALID_URL.value,
    ProcessingStatus.QUEUE_FAILED.value,
    ProcessingStatus.CANCELLED.value,
}


def has_active_processing_rows(rows: list[SheetRow]) -> bool:
    return any(str(row.status or "").strip() not in {"", *TERMINAL_SHEET_STATUSES} for row in rows)


def sort_rows_for_usage(rows: list[SheetRow]) -> list[SheetRow]:
    return sorted(rows, key=sheet_usage_sort_key)


def sheet_usage_sort_key(row: SheetRow) -> tuple[int, float]:
    is_used = normalize_used_value(row.used)
    timestamp = row.used_at if is_used else row.created_at
    fallback_timestamp = row.created_at if is_used else ""
    return (1 if is_used else 0, -parse_sheet_timestamp(timestamp or fallback_timestamp))


def parse_sheet_timestamp(value: str) -> float:
    value = str(value or "").strip()
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def used_sync_updates(
    rows_by_tab: dict[str, list[tuple[int, SheetRow]]],
    *,
    used: bool,
    inspiration_folder_link: str = "",
    shortcode: str = "",
    reel_url: str = "",
    edited_tab_name: str = "",
    edited_row_number: int | None = None,
    used_at: str = "",
) -> list[tuple[str, int]]:
    updates: list[tuple[str, int]] = []
    wanted_used_at = used_at if used else ""
    for tab_name, rows in rows_by_tab.items():
        for row_index, row in rows:
            if tab_name == edited_tab_name and row_index == edited_row_number:
                continue
            if not sheet_row_matches_reference(
                row,
                inspiration_folder_link=inspiration_folder_link,
                shortcode=shortcode,
                reel_url=reel_url,
            ):
                continue
            if normalize_used_value(row.used) == used and row.used_at == wanted_used_at:
                continue
            updates.append((tab_name, row_index))
    return updates


def sheet_row_matches_reference(
    row: SheetRow,
    *,
    inspiration_folder_link: str = "",
    shortcode: str = "",
    reel_url: str = "",
) -> bool:
    wanted_folder_id = extract_drive_folder_id_from_link(inspiration_folder_link)
    row_folder_id = extract_drive_folder_id_from_link(row.inspiration_folder_link)
    if wanted_folder_id and row_folder_id and wanted_folder_id == row_folder_id:
        return True

    if shortcode and row.shortcode and shortcode == row.shortcode:
        return True

    if reel_url and row.reel_url and reel_url == row.reel_url:
        return True

    return False
