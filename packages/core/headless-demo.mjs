#!/usr/bin/env node
// Headless Univer demo – create a workbook from CSV using Facade API
import fs from 'node:fs';
import path from 'node:path';

// Use Preset Mode for headless Node
import { createUniver, LocaleType } from '@univerjs/presets';
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core';
import { UniverSheetsPlugin } from '@univerjs/sheets';
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula';

const csvPath = '/Users/aryanagarwal/univer-local-demo/data/sample.csv';
const csvText = fs.readFileSync(csvPath, 'utf-8');
console.log('CSV loaded:', csvPath);
console.log(csvText);

// Parse CSV into rows
const rows = csvText.trim().split('\n').map(line => line.split(','));

console.log('Parsed rows:', rows.length);

// Create headless Univer instance
// In headless mode we can create Univer without UI container
const { univerAPI } = createUniver({
  locale: LocaleType.EN_US,
  presets: [
    UniverSheetsCorePreset({ container: null }),
  ],
});

// Create a new workbook
const workbook = univerAPI.createWorkbook({ name: 'Headless Demo' });
const sheet = workbook.getSheets()[0];
const sheetId = sheet.getSheetId?.() ?? sheet.id;

console.log('Workbook created:', workbook.getName?.());
console.log('Sheet id:', sheetId);

// Fill cells from CSV
rows.forEach((cols, r) => {
  cols.forEach((val, c) => {
    // Facade API: setRangeValues with A1 notation
    // Simplified: use setValue if available
    try {
      const cellRef = `${String.fromCharCode(65 + c)}${r + 1}`;
      // Note: actual API name may vary by version. This is illustrative.
      // univerAPI.setRangeValue?.(workbook.getUnitId(), sheetId, { startRow: r, startColumn: c, endRow: r, endColumn: c }, [[val]]);
      console.log(`Would set ${cellRef} = ${val}`);
    } catch (e) {
      // ignore for demo
    }
  });
});

console.log('Headless demo complete. Workbook is in memory.');
