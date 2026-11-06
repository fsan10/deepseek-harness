/**
 * Browser-safe wire views of the `authorization` Remote namespace.
 *
 * The controller projects seam interactions onto these shapes so a page can
 * drive a sign-in over unary HTTP calls; no callback, secret, or AbortSignal
 * crosses the request boundary.
 *
 * @module @deepseek-ai/dsh-api-authorization-controller/types
 */

declare module '@deepseek-ai/dsh-typert-protocol' {
  interface RemoteErrorDetailsMap {
    /** A sign-in flow's begin or answer was refused for an addressable credential. */
    'authorization/rejected': { readonly key: string }
  }
}

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
