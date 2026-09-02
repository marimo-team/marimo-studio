export class ExactPageRetirementWitness<Owner extends object> {
  private readonly owners = new Set<Owner>();
  private closed = false;
  private invalidRecovery = false;
  private isRecovered = false;

  recordOwner(owner: Owner): void {
    if (!this.closed && !this.isRecovered) {
      this.owners.add(owner);
    }
  }

  recordAbort(owner: Owner, errorText: string): boolean {
    if (errorText !== "net::ERR_ABORTED" || !this.owners.has(owner)) {
      return false;
    }
    return true;
  }

  recordClosed(): void {
    this.closed = true;
  }

  recover(pageIsClosed: boolean): boolean {
    if (!this.closed || !pageIsClosed) {
      this.invalidRecovery = true;
      return false;
    }
    this.isRecovered = true;
    return true;
  }

  owned(): readonly Owner[] {
    return [...this.owners];
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    if (this.invalidRecovery) {
      messages.push("expected page retirement recovered before the page closed");
    }
    if (!this.closed) {
      messages.push("expected page retirement observed no page close");
    } else if (!this.isRecovered) {
      messages.push("expected page retirement had no observed recovery");
    }
    return messages;
  }
}
