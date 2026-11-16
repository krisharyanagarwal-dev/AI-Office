#!/usr/bin/env node
// Headless Univer: read CSV -> build IWorkbookData -> create workbook -> save JSON snapshot
import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import { Univer } from '@univerjs/core';
import { UniverSheetsPlugin } from '@univerjs/sheets';
import { FUniver } from '@univerjs/core/facade';
import '@univerjs/sheets/facade';

const csvPath = '/Users/aryanagarwal/univer-local-demo/data/sample.csv';
const outPath = '/Users/aryanagarwal/univer-local-demo/data/univer-output.json';

const csv = fs.readFileSync(csvPath, 'utf-8').trim();
const rows = csv.split('\n').map(l => l.split(','));

const sheetId = randomUUID();
const workbookId = randomUUID();

function buildWorkbookData(rows) {
  const cellData = {};
  rows.forEach((cols, r) => {
    cellData[r] = {};
    cols.forEach((val, c) => {
      // t:1 = string, t:2 = number – naive detection
      const num = Number(val);
      const isNum = !Number.isNaN(num) && val.trim() !== '' && /^-?\d+(\.\d+)?$/.test(val.trim());
      cellData[r][c] = { v: isNum ? num : val, t: isNum ? 2 : 1 };
    });
  });

  return {
    id: workbookId,
    name: 'CSV Import',
    appVersion: '1',
    locale: 'enUS',
    styles: {},
    sheetOrder: [sheetId],
    sheets: {
      [sheetId]: {
        id: sheetId,
        name: 'Sheet1',
        rowCount: rows.length,
        columnCount: Math.max(...rows.map(r => r.length)),
        cellData,
      },
    },
  };
}

const workbookData = buildWorkbookData(rows);

const univer = new Univer();
univer.registerPlugin(UniverSheetsPlugin);
const api = FUniver.newAPI(univer);

const workbook = api.createWorkbook(workbookData);
console.log('Workbook created:', workbook.getName?.() ?? workbookData.name);
console.log('Unit ID:', workbook.getUnitId?.() ?? workbookId);

// Save snapshot to JSON
const snapshot = workbook.save?.() ?? workbookData;
fs.writeFileSync(outPath, JSON.stringify(snapshot, null, 2));
console.log('Snapshot saved to', outPath);
console.log('Rows:', rows.length, 'Cols:', Math.max(...rows.map(r => r.length)));
