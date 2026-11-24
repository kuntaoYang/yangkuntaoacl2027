// Track revision-specific checks without equating local execution with benchmark success.
export class EvidenceLedger {
  constructor(revision, maxReminders = 2) {
    this.revision = revision;
    this.initialRevision = revision;
    this.maxReminders = maxReminders;
    this.reminders = 0;
    this.checks = [];
    this.openFailures = new Map();
  }

  observeRevision(revision) {
    this.revision = revision;
  }

  record(check) {
    this.checks.push(check);
    if (check.accepted) this.openFailures.delete(check.key);
    else this.openFailures.set(check.key, check);
  }

  status() {
    const fresh = this.checks.filter(c => c.accepted && c.kind !== "observed_bash" && c.revision === this.revision);
    return {
      revision: this.revision,
      sourceChanged: this.revision !== this.initialRevision,
      freshChecks: fresh.length,
      unresolvedCheckKeys: [...this.openFailures.keys()],
      ready: fresh.length > 0 && this.openFailures.size === 0,
      reminders: this.reminders,
      semanticCoverage: "not_proven",
      officialOutcome: "pending",
    };
  }

  nextReminder() {
    if (this.status().ready || this.reminders >= this.maxReminders) return undefined;
    this.reminders += 1;
    return "H1 validation review: there is no accepted check of the current source revision, or a previous observed check is still unresolved. " +
      "Use verify_task to run a real target scenario or repository test. Include the actual modified Python module(s), explicit acceptance criteria, and a regression intent. " +
      "A copied condition, import-only check, zero collected tests, or another task's installed source is insufficient. Re-run the same failed check after repair. " +
      "If execution is blocked, report the blocker and remaining uncertainty honestly. Local checks do not establish official SWE-bench success. " +
      JSON.stringify(this.status());
  }
}
