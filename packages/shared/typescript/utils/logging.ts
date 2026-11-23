/**
 * Structured logging utilities for TypeScript packages.
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  service: string;
  message: string;
  fields: Record<string, any>;
}

export class JSONFormatter {
  private serviceName: string;

  constructor(serviceName: string = 'ai-office') {
    this.serviceName = serviceName;
  }

  format(level: LogLevel, message: string, fields: Record<string, any> = {}): string {
    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      service: fields.service || this.serviceName,
      message,
      fields: { ...fields },
    };

    // Remove service from fields if present
    delete entry.fields.service;

    return JSON.stringify(entry);
  }
}

export interface LoggerOptions {
  serviceName?: string;
  level?: LogLevel;
  console?: boolean;
}

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

export class StructuredLogger {
  private formatter: JSONFormatter;
  private minLevel: LogLevel;
  private context: Record<string, any>;
  private console: boolean;

  constructor(options: LoggerOptions = {}) {
    this.formatter = new JSONFormatter(options.serviceName || 'ai-office');
    this.minLevel = options.level || 'info';
    this.context = {};
    this.console = options.console !== false;
  }

  private shouldLog(level: LogLevel): boolean {
    return LEVEL_PRIORITY[level] >= LEVEL_PRIORITY[this.minLevel];
  }

  private log(level: LogLevel, message: string, fields: Record<string, any> = {}): void {
    if (!this.shouldLog(level)) return;

    const mergedFields = { ...this.context, ...fields };
    const output = this.formatter.format(level, message, mergedFields);

    if (this.console) {
      const consoleMethod = level === 'error' ? console.error : 
                           level === 'warn' ? console.warn : 
                           console.log;
      consoleMethod(output);
    }
  }

  debug(message: string, fields?: Record<string, any>): void {
    this.log('debug', message, fields);
  }

  info(message: string, fields?: Record<string, any>): void {
    this.log('info', message, fields);
  }

  warn(message: string, fields?: Record<string, any>): void {
    this.log('warn', message, fields);
  }

  error(message: string, fields?: Record<string, any>): void {
    this.log('error', message, fields);
  }

  withContext(context: Record<string, any>): StructuredLogger {
    const logger = new StructuredLogger({
      serviceName: this.formatter['serviceName'],
      level: this.minLevel,
      console: this.console,
    });
    logger.context = { ...this.context, ...context };
    return logger;
  }

  setLevel(level: LogLevel): void {
    this.minLevel = level;
  }
}

// Global logger cache
const loggers: Map<string, StructuredLogger> = new Map();

export function getLogger(serviceName: string, options?: LoggerOptions): StructuredLogger {
  if (!loggers.has(serviceName)) {
    loggers.set(serviceName, new StructuredLogger({ ...options, serviceName }));
  }
  return loggers.get(serviceName)!;
}

export function createLogger(options: LoggerOptions): StructuredLogger {
  return new StructuredLogger(options);
}