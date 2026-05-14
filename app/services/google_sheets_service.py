from __future__ import annotations

import re

from googleapiclient.discovery import build

from app.config import Settings
from app.models.schemas import ContentPillar, SHEET_COLUMNS, SheetRow
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
