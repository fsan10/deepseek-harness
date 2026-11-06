/**
 * Host owner of the `authorization` Remote namespace: the human-guided sign-in
 * half of `ctx.authorization` as a browser configuration page drives it.
 *
 * A Web page cannot hold a callback object across an HTTP request, so the
 * seam's `notify`/`prompt` interaction is projected onto a short-lived attempt
 * record: `start()` launches the flow, `poll()` reads its accumulated notices
 * and current question, `answer()` supplies that question's value, and
 * `finish()` withdraws the attempt. Only the page holding the attempt id can
 * answer its prompts, which keeps the interaction with the surface that asked.
 *
 * A plugin of its own rather than part of the settings controller: a
 * composition that has no configuration surfaces still wants sign-in flows,
 * and one that has them can drop this namespace without the settings owner.
 *
 * @module @deepseek-ai/dsh-api-authorization-controller
 */

import { randomUUID } from 'node:crypto'
import { Context } from '@deepseek-ai/cordis'
import { parseCredentialKey } from '@deepseek-ai/dsh-credentials'
import type { CredentialKey } from '@deepseek-ai/dsh-credentials'
import type { AuthorizationService } from '@deepseek-ai/dsh-authorization'
import type { AuthorizationNotice, AuthorizationPrompt } from '@deepseek-ai/dsh-authorization/types'
import { Remote, RemoteError, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import type {
  AuthorizationAttemptView, AuthorizationFlowView,
  AuthorizationNoticeView, AuthorizationPromptView,
} from './types.ts'

/** One running sign-in, holding the interaction state between unary calls. */
interface Attempt {
  readonly key: CredentialKey
  readonly controller: AbortController
  readonly notices: AuthorizationNoticeView[]
  // Required but nullable: `exactOptionalPropertyTypes` refuses assigning
  // `undefined` to an optional member, and clearing these is the whole point.
  prompt: AuthorizationPromptView | undefined
  answer: ((value: string) => void) | undefined
  status: AuthorizationAttemptView['status']
  error: string | undefined
}

/** Project a seam notice into the wire view, copying only declared fields. */
function noticeView(notice: AuthorizationNotice): AuthorizationNoticeView {
  return {
    message: notice.message,
    ...notice.url === undefined ? {} : { url: notice.url },
    ...notice.code === undefined ? {} : { code: notice.code },
  }
}

/**
 * Project a prompt onto the wire. Its own `signal` withdraws one question while
 * the flow keeps running; a page cannot carry an AbortSignal across requests,
 * so the whole attempt is withdrawn through `finish()` instead.
 */
function promptView(prompt: AuthorizationPrompt): AuthorizationPromptView {
  if (prompt.kind === 'select') {
    return {
      kind: 'select',
      message: prompt.message,
      options: prompt.options.map(option => ({
        id: option.id,
        label: option.label,
        ...option.description === undefined ? {} : { description: option.description },
      })),
    }
  }
  return {
    kind: prompt.kind,
    message: prompt.message,
    ...prompt.placeholder === undefined ? {} : { placeholder: prompt.placeholder },
  }
}

declare module '@deepseek-ai/cordis' {
  interface Context {
    /** Host owner of the `authorization` Remote namespace. */
    authorizationController: AuthorizationController
  }
}

/**
 * Host service backing the generated `ctx.remote.authorization` namespace.
 * Every method reports an actionable error when the authorization seam is not
 * mounted, and no method ever returns a secret: the credential itself stays in
 * the credential store, written by the flow that owns it.
 */
export class AuthorizationController extends TypertRemoteService {
  private readonly attempts = new Map<string, Attempt>()

  /** @param ctx - Host context where an authorization service may be mounted. */
  constructor(ctx: Context) {
    super(ctx, 'authorizationController', { namespace: 'authorization' })
  }

  /** Resolve the optional seam or report how to supply it. */
  private service(): AuthorizationService {
    const authorization = this.ctx.get('authorization')
    if (authorization === undefined) {
      throw new RemoteError(
        'gateway/internal',
        'authorization service is absent: this deployment does not mount @deepseek-ai/dsh-authorization in its composition',
        {},
      )
    }
    return authorization
  }

  /** Resolve one live attempt or refuse an id the caller does not own. */
  private attempt(id: string): Attempt {
    const attempt = this.attempts.get(id)
    if (attempt === undefined) {
      throw new RemoteError('authorization/rejected', `no authorization attempt "${id}" is running`, { key: id })
    }
    return attempt
  }

  /** Parse a `<scope>/<id>` key arriving from a configuration surface. */
  private keyOf(value: string): CredentialKey {
    try {
      return parseCredentialKey(value)
    } catch (error) {
      throw new RemoteError('gateway/bad-request', `invalid credential key "${value}"`, {}, { cause: error })
    }
  }

  /**
   * List every sign-in a surface may offer, with its preferred method first.
   * @returns the registered flows, keyed by their credential record address.
   */
  @Remote
  list(): AuthorizationFlowView[] {
    return this.service().list().map(entry => ({
      key: String(entry.key),
      label: entry.label,
      methods: entry.methods.map(method => ({ id: method.id, label: method.label })),
      inFlight: entry.inFlight,
    }))
  }

  /**
   * Start one sign-in without waiting for it. The flow runs against an
   * interaction that records notices and holds at most one unanswered prompt;
   * the page polls the returned id until the attempt settles.
   * @param keyValue - the `<scope>/<id>` credential address a flow registered.
   * @param method - one of that flow's method ids; omission takes its first.
   * @returns the attempt id, which is also the capability to answer its prompts.
   */
  @Remote
  start(keyValue: string, method: string | undefined): string {
    const key = this.keyOf(keyValue)
    const authorization = this.service()
    const entry = authorization.describe(key)
    if (entry === undefined) {
      throw new RemoteError('authorization/rejected', `no sign-in is registered for "${keyValue}"`, { key: keyValue })
    }
    if (method !== undefined && !entry.methods.some(candidate => candidate.id === method)) {
      throw new RemoteError(
        'authorization/rejected', `sign-in for "${keyValue}" offers no method "${method}"`, { key: keyValue })
    }
    const id = randomUUID()
    const attempt: Attempt = {
      key,
      controller: new AbortController(),
      notices: [],
      prompt: undefined,
      answer: undefined,
      status: 'running',
      error: undefined,
    }
    this.attempts.set(id, attempt)
    void authorization.begin({
      key,
      // Omitting `method` takes the flow's first one; passing an explicit
      // `undefined` is refused under `exactOptionalPropertyTypes`.
      ...method === undefined ? {} : { method },
      signal: attempt.controller.signal,
      interaction: {
        notify: (notice) => { attempt.notices.push(noticeView(notice)) },
        prompt: prompt => new Promise<string>((resolve) => {
          attempt.prompt = promptView(prompt)
          attempt.answer = resolve
        }),
      },
    }).then((outcome) => { attempt.status = outcome.status })
      .catch((error: unknown) => {
        attempt.status = 'failed'
        attempt.error = error instanceof Error ? error.message : String(error)
      })
      .finally(() => { attempt.prompt = undefined; attempt.answer = undefined })
    return id
  }

  /**
   * Read one attempt's current state. Notices accumulate for the whole attempt;
   * a page renders the newest one and keeps earlier ones for context.
   * @param id - the attempt id `start()` returned.
   * @returns status, notices, and the question currently waiting, if any.
   */
  @Remote
  poll(id: string): AuthorizationAttemptView {
    const attempt = this.attempt(id)
    return {
      status: attempt.status,
      notices: [...attempt.notices],
      ...attempt.prompt === undefined ? {} : { prompt: attempt.prompt },
      ...attempt.error === undefined ? {} : { error: attempt.error },
    }
  }

  /**
   * Supply the value for the question `poll()` reported. A second answer for
   * the same question is refused rather than silently ignored.
   * @param id - the attempt id.
   * @param value - the text, secret, or selected option id the human supplied.
   */
  @Remote
  answer(id: string, value: string): void {
    const attempt = this.attempt(id)
    if (attempt.answer === undefined) {
      throw new RemoteError('authorization/rejected', `attempt "${id}" has no question waiting`, { key: id })
    }
    const resolve = attempt.answer
    attempt.answer = undefined
    attempt.prompt = undefined
    resolve(value)
  }

  /** Withdraw the sign-in running for one credential key. */
  @Remote
  cancel(keyValue: string): void {
    const key = this.keyOf(keyValue)
    this.service().cancel(key)
  }

  /**
   * Release a settled attempt. Aborting its signal withdraws a flow that is
   * still waiting on a prompt, and answering that prompt with an empty value
   * releases the orphaned promise without letting it keep the process alive.
   * @param id - the attempt id.
   */
  @Remote
  finish(id: string): void {
    const attempt = this.attempt(id)
    this.attempts.delete(id)
    attempt.controller.abort()
    attempt.answer?.('')
    attempt.answer = undefined
  }
}

export type * from './types.ts'

/**
 * Mount the `authorization` Remote namespace as a plugin of its own.
 *
 * The class is also exported so a composition that owns its mount can use it
 * directly; installing this package is the ordinary path.
 * @param ctx - the context carrying `ctx.authorization`.
 */
export function apply(ctx: Context): void {
  ctx.plugin(AuthorizationController)
}
