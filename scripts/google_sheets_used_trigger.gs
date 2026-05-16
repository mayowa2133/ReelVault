/**
 * ReelVault Google Sheets Used checkbox trigger.
 *
 * Setup:
 * 1. Open the ReelVault Google Sheet.
 * 2. Extensions > Apps Script.
 * 3. Paste this file into the Apps Script editor.
 * 4. Set REELVAULT_BASE_URL and SHEETS_WEBHOOK_SECRET in configureReelVaultUsedWebhook.
 * 5. Run configureReelVaultUsedWebhook once.
 * 6. Run installReelVaultUsedTrigger once and approve permissions.
 */

function configureReelVaultUsedWebhook() {
  PropertiesService.getScriptProperties().setProperties({
    REELVAULT_BASE_URL: 'https://reelvault-446674815802.us-central1.run.app',
    SHEETS_WEBHOOK_SECRET: 'PASTE_SHEETS_WEBHOOK_SECRET_HERE',
  });
}

function installReelVaultUsedTrigger() {
  const spreadsheet = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers()
    .filter((trigger) => trigger.getHandlerFunction() === 'reelVaultUsedOnEdit')
    .forEach((trigger) => ScriptApp.deleteTrigger(trigger));

  ScriptApp.newTrigger('reelVaultUsedOnEdit')
    .forSpreadsheet(spreadsheet)
    .onEdit()
    .create();
}

function reelVaultUsedOnEdit(e) {
  if (!e || !e.range) {
    return;
  }

  const range = e.range;
  if (range.getRow() === 1 || range.getNumRows() !== 1 || range.getNumColumns() !== 1) {
    return;
  }

  const sheet = range.getSheet();
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const usedColumn = headers.indexOf('Used') + 1;
  if (!usedColumn || range.getColumn() !== usedColumn) {
    return;
  }

  const rowValues = sheet.getRange(range.getRow(), 1, 1, headers.length).getValues()[0];
  const payload = {
    sheetName: sheet.getName(),
    rowNumber: range.getRow(),
    used: range.getValue() === true || String(range.getValue()).toUpperCase() === 'TRUE',
    pillar: valueForHeader(headers, rowValues, 'Pillar'),
    shortcode: valueForHeader(headers, rowValues, 'Shortcode'),
    reelUrl: valueForHeader(headers, rowValues, 'Reel URL'),
    inspirationFolderLink: valueForHeader(headers, rowValues, 'Inspiration Folder Link'),
  };

  const properties = PropertiesService.getScriptProperties();
  const baseUrl = properties.getProperty('REELVAULT_BASE_URL');
  const secret = properties.getProperty('SHEETS_WEBHOOK_SECRET');
  if (!baseUrl || !secret || secret === 'PASTE_SHEETS_WEBHOOK_SECRET_HERE') {
    SpreadsheetApp.getActive().toast('ReelVault Used trigger is missing URL or secret.', 'ReelVault', 8);
    return;
  }

  const response = UrlFetchApp.fetch(baseUrl.replace(/\/$/, '') + '/webhook/sheets/used', {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'X-ReelVault-Sheets-Secret': secret,
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  const statusCode = response.getResponseCode();
  if (statusCode < 200 || statusCode >= 300) {
    SpreadsheetApp.getActive().toast(
      'ReelVault folder move failed: HTTP ' + statusCode,
      'ReelVault',
      8
    );
  }
}

function valueForHeader(headers, rowValues, headerName) {
  const index = headers.indexOf(headerName);
  if (index === -1) {
    return '';
  }
  const value = rowValues[index];
  return value === null || value === undefined ? '' : String(value);
}
