/**
 * Centralized path resolution for Zoeae
 *
 * ONE source of truth for all data paths.
 * Resolution order: env var > config > sensible default
 *
 * AnnulusLabs LLC
 */

import { join } from "node:path";
import { existsSync, mkdirSync } from "node:fs";

/** Resolve the base KERF data directory */
export function getKerfDir(): string {
  const dir =
    process.env.ZOEAE_DATA ??
    process.env.KERF_DIR ??
    join(process.env.HOME ?? process.env.USERPROFILE ?? ".", ".zoeae", "data");
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  return dir;
}

/** Resolve specific data paths */
export const paths = {
  /** Agent pool persistence */
  agentPool: () => join(getKerfDir(), "agent-pool.json"),

  /** Dream journal */
  dreamJournal: () => join(getKerfDir(), "dreams.jsonl"),

  /** Audit trail */
  auditLog: () => join(getKerfDir(), "audit.jsonl"),

  /** Cron jobs persistence */
  cronJobs: () => join(getKerfDir(), "cron-jobs.json"),

  /** Knowledge paths for dream engine fact pool */
  knowledgePaths: (): string[] => {
    const custom = process.env.ZOEAE_KNOWLEDGE_PATHS;
    if (custom) return custom.split(";").filter(Boolean);
    // Default: scan KERF dir + session log
    const kerf = getKerfDir();
    const paths = [kerf];
    const sessionLog = join(
      process.env.HOME ?? process.env.USERPROFILE ?? ".",
      ".openclaw", "workspace", "activity.jsonl",
    );
    if (existsSync(sessionLog)) paths.push(sessionLog);
    return paths;
  },

  /** Mail log */
  mailLog: () =>
    process.env.OPENCLAW_MAIL_LOG ?? join(getKerfDir(), "mail_log.jsonl"),

  /** Mail config */
  mailConfig: () =>
    process.env.OPENCLAW_MAIL_CONFIG ?? join(getKerfDir(), "mail_config.json"),
};
