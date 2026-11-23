/**
 * File I/O utilities for TypeScript packages.
 * Note: These are Node.js implementations. For browser, use appropriate alternatives.
 */

import * as fs from 'fs';
import * as path from 'path';

export function ensureDir(dirPath: string): void {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

export function readJson<T>(filePath: string, defaultValue?: T): T | undefined {
  try {
    if (!fs.existsSync(filePath)) {
      return defaultValue;
    }
    const content = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(content);
  } catch {
    return defaultValue;
  }
}

export function writeJson(filePath: string, data: any, indent: number = 2): boolean {
  try {
    const dir = path.dirname(filePath);
    ensureDir(dir);
    fs.writeFileSync(filePath, JSON.stringify(data, null, indent), 'utf-8');
    return true;
  } catch {
    return false;
  }
}

export function readYaml(filePath: string): any {
  try {
    if (!fs.existsSync(filePath)) {
      return undefined;
    }
    // Use js-yaml if available
    const yaml = require('js-yaml');
    const content = fs.readFileSync(filePath, 'utf-8');
    return yaml.load(content);
  } catch {
    return undefined;
  }
}

export function writeYaml(filePath: string, data: any): boolean {
  try {
    const dir = path.dirname(filePath);
    ensureDir(dir);
    const yaml = require('js-yaml');
    fs.writeFileSync(filePath, yaml.dump(data), 'utf-8');
    return true;
  } catch {
    return false;
  }
}

export function readText(filePath: string, defaultValue: string = ''): string {
  try {
    if (!fs.existsSync(filePath)) {
      return defaultValue;
    }
    return fs.readFileSync(filePath, 'utf-8');
  } catch {
    return defaultValue;
  }
}

export function writeText(filePath: string, content: string): boolean {
  try {
    const dir = path.dirname(filePath);
    ensureDir(dir);
    fs.writeFileSync(filePath, content, 'utf-8');
    return true;
  } catch {
    return false;
  }
}

export function listFiles(dirPath: string, pattern: string = '*', recursive: boolean = false): string[] {
  if (!fs.existsSync(dirPath)) {
    return [];
  }
  
  const files: string[] = [];
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory() && recursive) {
      files.push(...listFiles(fullPath, pattern, true));
    } else if (entry.isFile() && matchPattern(entry.name, pattern)) {
      files.push(fullPath);
    }
  }
  
  return files;
}

function matchPattern(filename: string, pattern: string): boolean {
  // Simple glob matching
  const regex = pattern
    .replace(/\./g, '\\.')
    .replace(/\*/g, '.*')
    .replace(/\?/g, '.');
  return new RegExp(`^${regex}$`).test(filename);
}

export function getFileSize(filePath: string): number {
  try {
    const stats = fs.statSync(filePath);
    return stats.isFile() ? stats.size : 0;
  } catch {
    return 0;
  }
}

export function copyFile(src: string, dst: string): boolean {
  try {
    ensureDir(path.dirname(dst));
    fs.copyFileSync(src, dst);
    return true;
  } catch {
    return false;
  }
}