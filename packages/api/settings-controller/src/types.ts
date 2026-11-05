/**
 * Browser-safe failure vocabulary of the configuration surfaces this package
 * serves. The redacted views themselves live with their seam in
 * `@deepseek-ai/dsh-settings/types`, whose Cordis event declarations already
 * register that file for the Client compilation face.
 *
 * @module @deepseek-ai/dsh-api-settings-controller/types
 */

declare module '@deepseek-ai/dsh-typert-protocol' {
  interface RemoteErrorDetailsMap {
    /**
     * Every seam refusal that is not a stale write: an unregistered or malformed
     * namespace, a read-only provider, schema validation, storage.
     */
    'settings/rejected': { readonly ns: string }
    /**
     * The stored revision moved after the caller read it. Its own outcome rather
     * than an invalid request: the caller must re-read and re-apply.
     */
    'settings/conflict': { readonly ns: string; readonly expected: number; readonly actual: number }
    /**
     * The provider refused a valid credential write, for example because a
     * read-only source shadows the reference. The details name only the
     * reference, never the value.
     */
    'credential/rejected': { readonly ref: string }
    /**
     * An authorization attempt was refused: no flow owns the key, the named
     * method is not one it offers, or the attempt id is unknown or stale.
     */
    'authorization/rejected': { readonly key: string }
  }
}

/** Confirmation that the settings document was handed to the native editor. */
export interface SettingsDocumentOpenValue {
  readonly opened: true
}

/** Result of opening or revealing one locally authored Agent preset directory. */
export type AgentPresetDirectoryOpenValue =
  | { readonly opened: true }
  | { readonly opened: false; readonly path: string }

/** One sign-in a configuration surface may offer, with its methods in preference order. */
export interface AuthorizationFlowView {
  /** `<scope>/<id>` credential record address the flow writes. */
  readonly key: string
  /** User-facing name of what is being authorized. */
  readonly label: string
  readonly methods: readonly { readonly id: string; readonly label: string }[]
  /** Whether another surface already has an attempt running for this key. */
  readonly inFlight: boolean
}

/** One notice a flow raised for the human; never carries a secret. */
export interface AuthorizationNoticeView {
  readonly message: string
  readonly url?: string
  readonly code?: string
}

/** The wire-safe form of one question: no AbortSignal crosses the request boundary. */
export type AuthorizationPromptView =
  | { readonly kind: 'text' | 'secret'; readonly message: string; readonly placeholder?: string }
  | {
    readonly kind: 'select'
    readonly message: string
    readonly options: readonly {
      readonly id: string
      readonly label: string
      readonly description?: string
    }[]
  }

/** One poll of a running sign-in. */
export interface AuthorizationAttemptView {
  readonly status: 'running' | 'authorized' | 'cancelled' | 'failed'
  /** Every notice raised so far, oldest first. */
  readonly notices: readonly AuthorizationNoticeView[]
  /** The question currently waiting for an answer, when there is one. */
  readonly prompt?: AuthorizationPromptView
  /** Failure text when the flow itself broke, never a credential value. */
  readonly error?: string
}
