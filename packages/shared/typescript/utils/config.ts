/**
 * Configuration utilities for TypeScript packages.
 */

export interface ConfigLoaderOptions {
  configDir?: string;
  envPrefix?: string;
}

export class ConfigLoader {
  private configDir: string;
  private envPrefix: string;
  private cache: Map<string, any> = new Map();

  constructor(options: ConfigLoaderOptions = {}) {
    this.configDir = options.configDir || process.cwd() + '/config';
    this.envPrefix = options.envPrefix || 'OFFICE';
  }

  load(name: string): Record<string, any> {
    const cacheKey = `${name}:${this.envPrefix}`;
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey)!;
    }

    let config: Record<string, any> = {};

    // Try multiple file formats
    const fs = require('fs');
    const path = require('path');
    
    for (const ext of ['.yaml', '.yml', '.json']) {
      const configPath = path.join(this.configDir, `${name}${ext}`);
      if (fs.existsSync(configPath)) {
        config = this.loadFile(configPath);
        break;
      }
    }

    // Apply environment variable overrides
    config = this.applyEnvOverrides(config);

    this.cache.set(cacheKey, config);
    return config;
  }

  private loadFile(filePath: string): Record<string, any> {
    const fs = require('fs');
    const content = fs.readFileSync(filePath, 'utf-8');
    
    if (filePath.endsWith('.json')) {
      return JSON.parse(content);
    }
    
    // For YAML, use js-yaml if available
    try {
      const yaml = require('js-yaml');
      return yaml.load(content) || {};
    } catch {
      return {};
    }
  }

  private applyEnvOverrides(config: Record<string, any>): Record<string, any> {
    for (const [key, value] of Object.entries(process.env)) {
      if (key.startsWith(`${this.envPrefix}_`)) {
        // Convert OFFICE_DB_HOST -> db.host
        const configKey = key.slice(this.envPrefix.length + 1).toLowerCase().replace(/_/g, '.');
        this.setNested(config, configKey, this.parseValue(value));
      }
    }
    return config;
  }

  private setNested(obj: Record<string, any>, key: string, value: any): void {
    const parts = key.split('.');
    let current = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!(part in current)) {
        current[part] = {};
      }
      current = current[part];
    }
    current[parts[parts.length - 1]] = value;
  }

  private parseValue(value: string): any {
    // Try JSON first
    try {
      return JSON.parse(value);
    } catch {
      // Ignore
    }

    // Boolean
    if (value.toLowerCase() === 'true' || value === '1' || value.toLowerCase() === 'yes') {
      return true;
    }
    if (value.toLowerCase() === 'false' || value === '0' || value.toLowerCase() === 'no') {
      return false;
    }

    // Number
    if (!isNaN(Number(value))) {
      return value.includes('.') ? parseFloat(value) : parseInt(value, 10);
    }

    return value;
  }

  clearCache(): void {
    this.cache.clear();
  }
}

// Default config loader instance
export const defaultConfigLoader = new ConfigLoader();

export function loadConfig(name: string, options?: ConfigLoaderOptions): Record<string, any> {
  if (options) {
    return new ConfigLoader(options).load(name);
  }
  return defaultConfigLoader.load(name);
}

export function getConfig(name: string, key: string, defaultValue?: any): any {
  const config = loadConfig(name);
  const parts = key.split('.');
  let current: any = config;
  
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part];
    } else {
      return defaultValue;
    }
  }
  
  return current;
}