import i18n from '../i18n'
import { ONE_SHOT_COMMAND_NAMES } from '../api/commands'

// A Set (not an object lookup) so an untrusted name such as "__proto__" can never hit an
// inherited property; anything unknown renders as the raw string instead.
// `mode-waiting-now` is no longer sent but still appears in the command history.
const LEGACY_COMMANDS = ['mode-waiting-now']
const KNOWN_COMMANDS: ReadonlySet<string> = new Set([...ONE_SHOT_COMMAND_NAMES, ...LEGACY_COMMANDS])

type Translate = (key: string) => string

export function commandLabel(name: string, t: Translate = (key) => i18n.t(key)): string {
  return KNOWN_COMMANDS.has(name) ? t(`commands:${name}`) : name
}
