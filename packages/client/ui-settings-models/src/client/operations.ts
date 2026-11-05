/**
 * The Host reads and writes the Models cards perform, as callbacks built in the
 * plugin body. Cards receive these instead of a context: the outcomes name what
 * a card renders — a stored view, a stale revision, a refusal message — so the
 * failure codes and Remote namespaces stay in the apply world.
 */

import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type {
  AuthorizationAttemptView, AuthorizationFlowView,
  CredentialInfo, LlmDiscoveredModel, LlmModelDiscoveryRequest,
  SettingsNamespaceView, SettingsPathOpView,
} from '@deepseek-ai/dsh-api-remotes/client'

/** What one namespace write answered. */
export type SettingsWriteOutcome =
  /** Committed; the view carries the stored user subtree and the new revision. */
  | { readonly kind: 'written'; readonly view: SettingsNamespaceView }
  /**
   * The stored revision moved after the card read it, so the draft is stale.
   * The message stays for callers that report the Host diagnostic as it is.
   */
  | { readonly kind: 'conflict'; readonly message: string }
  /** Any other refusal, with the Host's own diagnostic. */
  | { readonly kind: 'refused'; readonly message: string }

/** What one authorization Remote call answered. */
export type AuthorizationCall<T> =
  | { readonly kind: 'ok'; readonly value: T }
  | { readonly kind: 'refused'; readonly message: string }

/** What one endpoint interrogation answered. */
export type ModelDiscoveryOutcome =
  /** The candidates the provider disclosed, in its own order. */
  | { readonly kind: 'found'; readonly models: readonly LlmDiscoveredModel[] }
  /** The interrogation was refused, with the Host's own diagnostic. */
  | { readonly kind: 'refused'; readonly message: string }

/** The Host operations the Models page and its cards invoke. */
export interface ModelsOperations {
  /**
   * Read one credential reference's state.
   * @param ref - credential reference name.
   * @returns the state, or undefined when the reference is unknown or the read was refused.
   */
  describeCredential(ref: string): Promise<CredentialInfo | undefined>
  /**
   * Store one credential literal under its reference.
   * @param ref - credential reference name.
   * @param value - the literal to store.
   * @returns the refusal message, or undefined once stored.
   */
  storeCredential(ref: string, value: string): Promise<string | undefined>
  /**
   * Remove one credential reference (idempotent).
   * @param ref - credential reference name.
   * @returns the refusal message, or undefined once removed.
   */
  removeCredential(ref: string): Promise<string | undefined>
  /**
   * Apply path operations to one settings namespace.
   * @param ns - settings namespace identity.
   * @param ops - ordered path operations against the stored section, as the
   * wire takes them (the Remote signature owns the array).
   * @param expectedRevision - revision the draft was opened at, or undefined to write unfenced.
   * @returns the write outcome the card renders from.
   */
  writeSettings(
    ns: string,
    ops: SettingsPathOpView[],
    expectedRevision: number | undefined,
  ): Promise<SettingsWriteOutcome>
  /**
   * Ask a provider endpoint what models it serves.
   * @param settingsNs - namespace whose adapter family answers.
   * @param request - endpoint facts as the form currently shows them.
   * @returns the candidates, or the refusal.
   */
  discoverModels(settingsNs: string, request: LlmModelDiscoveryRequest): Promise<ModelDiscoveryOutcome>
  /**
   * List the sign-in flows a provider adapter registered. An empty answer is
   * the honest "nothing to sign into" state, not a refused read.
   */
  listSignIns(): Promise<readonly AuthorizationFlowView[]>
  /** Start one sign-in and return the attempt id that answers its prompts. */
  startSignIn(key: string, method: string | undefined): Promise<AuthorizationCall<string>>
  /** Read one attempt's notices, question, and status. */
  pollSignIn(id: string): Promise<AuthorizationCall<AuthorizationAttemptView>>
  /** Supply the answer to the question a poll reported. */
  answerSignIn(id: string, value: string): Promise<string | undefined>
  /** Withdraw the sign-in running for a credential key. */
  cancelSignIn(key: string): Promise<void>
  /** Release a settled attempt on the Host. */
  finishSignIn(id: string): Promise<void>
}

/**
 * Bind the page's Host operations to the plugin's own Remote namespaces.
 * @param ctx - the page plugin's context, which declares `remote.credentials`,
 * `remote.llm`, and `remote.settings` in its own `inject`.
 * @returns the callbacks the section and its cards are injected with.
 */
export function createModelsOperations(ctx: ClientContext): ModelsOperations {
  return {
    describeCredential: async (ref) => {
      const response = await ctx.remote.credentials.describe([ref])
      return response.ok ? response.value[ref] : undefined
    },
    storeCredential: async (ref, value) => {
      const response = await ctx.remote.credentials.set(ref, value)
      return response.ok ? undefined : response.error.message
    },
    removeCredential: async (ref) => {
      const response = await ctx.remote.credentials.unset(ref)
      return response.ok ? undefined : response.error.message
    },
    writeSettings: async (ns, ops, expectedRevision) => {
      const response = await ctx.remote.settings.mutate(ns, ops, expectedRevision)
      if (response.ok) return { kind: 'written', view: response.value }
      const { code, message } = response.error
      return code === 'settings/conflict' ? { kind: 'conflict', message } : { kind: 'refused', message }
    },
    discoverModels: async (settingsNs, request) => {
      const response = await ctx.remote.llm.discoverModels(settingsNs, request)
      return response.ok
        ? { kind: 'found', models: response.value }
        : { kind: 'refused', message: response.error.message }
    },
    listSignIns: async () => {
      // A browser may be talking to an older Host without this namespace;
      // showing no sign-in is the honest state, not a broken Models page.
      try {
        const response = await ctx.remote.authorization.list()
        return response.ok ? response.value : []
      } catch {
        return []
      }
    },
    startSignIn: async (key, method) => {
      const response = await ctx.remote.authorization.start(key, method)
      return response.ok
        ? { kind: 'ok', value: response.value }
        : { kind: 'refused', message: response.error.message }
    },
    pollSignIn: async (id) => {
      const response = await ctx.remote.authorization.poll(id)
      return response.ok
        ? { kind: 'ok', value: response.value }
        : { kind: 'refused', message: response.error.message }
    },
    answerSignIn: async (id, value) => {
      const response = await ctx.remote.authorization.answer(id, value)
      return response.ok ? undefined : response.error.message
    },
    cancelSignIn: async (key) => {
      await ctx.remote.authorization.cancel(key)
    },
    finishSignIn: async (id) => {
      await ctx.remote.authorization.finish(id)
    },
  }
}
