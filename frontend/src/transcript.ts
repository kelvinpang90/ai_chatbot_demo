import type { ConversationDetail } from './api'

// Helpers for the console's reading of the audit log, kept out of component
// files: oxlint's only-export-components, which fast refresh needs.

// Priced by the backend (app/console/cost.py) at the moment each call happened,
// the same module the live console prices with. Two formulas for one number in
// one product is how the two screens end up disagreeing in front of a customer.
export function money(myr: number): string {
  return `RM ${myr.toFixed(4)}`
}

/** Every tool call this transcript already shows, by the id the live feed uses. */
export function toolUseIds(detail: ConversationDetail | null): Set<string> {
  const ids = new Set<string>()
  for (const message of detail?.messages ?? []) {
    for (const call of message.tool_calls) ids.add(call.tool_use_id)
  }
  return ids
}
