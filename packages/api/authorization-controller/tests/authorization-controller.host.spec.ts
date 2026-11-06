import { describe, expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import AuthorizationService from '@deepseek-ai/dsh-authorization'
import type { AuthorizationSession } from '@deepseek-ai/dsh-authorization'
import { credentialKey } from '@deepseek-ai/dsh-credentials'
import { remoteErrorOf, remoteMethods } from '@deepseek-ai/dsh-typert-protocol'
import { AuthorizationController } from '../src/index.ts'
import type { AuthorizationAttemptView } from '../src/types.ts'
import { MemoryCredentials } from '../../../credentials/credentials/tests/memory.ts'

const KEY = 'llm-pi-ai/openai'
const key = credentialKey('llm-pi-ai', 'openai')

type FlowRun = (session: AuthorizationSession, ctx: Context) => Promise<void>

/** Commit a record so a flow reaches the seam's `authorized` outcome. */
function commit(ctx: Context, value: string): Promise<void> {
  return ctx.credentials.modifyRecord(key, () => Promise.resolve({ kind: 'grant', payload: { value } }))
    .then(() => undefined)
}

/** Poll a running attempt until its view satisfies a predicate. */
async function until(
  controller: AuthorizationController,
  id: string,
  predicate: (view: AuthorizationAttemptView) => boolean,
): Promise<AuthorizationAttemptView> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const view = controller.poll(id)
    if (predicate(view)) return view
    await new Promise((resolve) => { setTimeout(resolve, 2) })
  }
  throw new Error('the authorization attempt did not reach the expected state')
}

async function boot(options: { register?: boolean; run?: FlowRun } = {}): Promise<{
  ctx: Context
  controller: AuthorizationController
}> {
  const ctx = new Context()
  await ctx.plugin(MemoryCredentials, {})
  await ctx.plugin(AuthorizationService)
  await ctx.plugin(AuthorizationController)
  const run: FlowRun = options.run ?? (async (session, owner) => {
    session.notify({ message: 'Open the sign-in page', url: 'https://auth.example/start', code: 'ABCD' })
    const value = await session.prompt({
      kind: 'text', message: 'Paste the callback URL', placeholder: 'https://127.0.0.1:1455/auth/callback',
    })
    await commit(owner, value)
  })
  if (options.register !== false) {
    ctx.authorization.registerFlow({
      key,
      label: 'OpenAI',
      methods: [{ id: 'oauth', label: 'Sign in with ChatGPT' }],
      run: session => run(session, ctx),
    })
  }
  return { ctx, controller: ctx.authorizationController }
}

function catchSync(call: () => unknown): unknown {
  try { call(); return undefined } catch (error: unknown) { return error }
}

describe('the authorization Remote namespace a configuration page drives', () => {
  it('publishes its own namespace and every interaction method', async () => {
    const { controller } = await boot()
    expect(controller.typertRemote.serviceKey).toBe('authorizationController')
    expect(controller.typertRemote.namespace).toBe('authorization')
    expect(remoteMethods(controller).map(entry => entry.method)).toEqual([
      'list', 'start', 'poll', 'answer', 'cancel', 'finish',
    ])
  })

  it('reports the actionable configuration error while no authorization service is mounted', async () => {
    const ctx = new Context()
    await ctx.plugin(AuthorizationController)
    const controller = ctx.authorizationController
    for (const call of [
      () => controller.list(),
      () => controller.start(KEY, undefined),
      () => { controller.cancel(KEY) },
    ]) {
      expect(remoteErrorOf(catchSync(call))).toMatchObject({ code: 'gateway/internal', details: {} })
    }
  })

  it('lists the flows a provider registered, with their preferred method first', async () => {
    const { controller } = await boot()
    expect(controller.list()).toEqual([{
      key: KEY,
      label: 'OpenAI',
      methods: [{ id: 'oauth', label: 'Sign in with ChatGPT' }],
      inFlight: false,
    }])
  })

  it('projects notices and a prompt, settles after an answer, and releases the attempt', async () => {
    const { controller } = await boot()
    const id = controller.start(KEY, 'oauth')
    const asking = await until(controller, id, view => view.prompt !== undefined)
    expect(asking.status).toBe('running')
    expect(asking.notices).toEqual([{
      message: 'Open the sign-in page', url: 'https://auth.example/start', code: 'ABCD',
    }])
    expect(asking.prompt).toEqual({
      kind: 'text', message: 'Paste the callback URL', placeholder: 'https://127.0.0.1:1455/auth/callback',
    })
    controller.answer(id, 'https://127.0.0.1:1455/auth/callback?code=x')
    const settled = await until(controller, id, view => view.status !== 'running')
    expect(settled.status).toBe('authorized')
    expect(() => { controller.answer(id, 'again') }).toThrow()
    controller.finish(id)
    expect(remoteErrorOf(catchSync(() => controller.poll(id))))
      .toMatchObject({ code: 'authorization/rejected' })
  })

  it('projects a select prompt and a notice with neither url nor code', async () => {
    const { controller } = await boot({
      run: async (session, ctx) => {
        session.notify({ message: 'Choose an account' })
        const chosen = await session.prompt({
          kind: 'select', message: 'Account',
          options: [{ id: 'a', label: 'First' }, { id: 'b', label: 'Second', description: 'Work' }],
        })
        await commit(ctx, chosen)
      },
    })
    const id = controller.start(KEY, undefined)
    const asking = await until(controller, id, view => view.prompt !== undefined)
    expect(asking.notices).toEqual([{ message: 'Choose an account' }])
    expect(asking.prompt).toEqual({
      kind: 'select', message: 'Account',
      options: [{ id: 'a', label: 'First' }, { id: 'b', label: 'Second', description: 'Work' }],
    })
    controller.answer(id, 'b')
    expect((await until(controller, id, view => view.status !== 'running')).status).toBe('authorized')
    controller.finish(id)
  })

  it('projects a secret prompt', async () => {
    const { controller } = await boot({
      run: async (session, ctx) => {
        const secret = await session.prompt({ kind: 'secret', message: 'Paste a key' })
        await commit(ctx, secret)
      },
    })
    const id = controller.start(KEY, 'oauth')
    expect((await until(controller, id, view => view.prompt !== undefined)).prompt)
      .toEqual({ kind: 'secret', message: 'Paste a key' })
    controller.answer(id, 'sk-test')
    expect((await until(controller, id, view => view.status !== 'running')).status).toBe('authorized')
    controller.finish(id)
  })

  it('withdraws a running sign-in through cancel', async () => {
    const { controller } = await boot({
      run: async (session, ctx) => {
        const value = await session.prompt({ kind: 'text', message: 'Paste the callback URL' })
        await commit(ctx, value)
      },
    })
    const id = controller.start(KEY, 'oauth')
    await until(controller, id, view => view.prompt !== undefined)
    controller.cancel(KEY)
    expect((await until(controller, id, view => view.status !== 'running')).status).toBe('cancelled')
    controller.finish(id)
  })

  it('reports a failed flow as an attempt outcome rather than an unhandled rejection', async () => {
    const { controller } = await boot({
      run: () => Promise.reject(new Error('the issuer refused')),
    })
    const id = controller.start(KEY, 'oauth')
    const settled = await until(controller, id, view => view.status !== 'running')
    expect(settled.status).toBe('failed')
    expect(settled.error).toBe('the issuer refused')
    controller.finish(id)
  })

  it('refuses a malformed key and an unregistered flow', async () => {
    const { controller } = await boot({ register: false })
    expect(remoteErrorOf(catchSync(() => controller.start('not-a-key', undefined))))
      .toMatchObject({ code: 'gateway/bad-request' })
    expect(remoteErrorOf(catchSync(() => controller.start('llm-pi-ai/missing', undefined))))
      .toMatchObject({ code: 'authorization/rejected' })
  })

  it('refuses a method the flow does not offer', async () => {
    const { controller } = await boot()
    expect(remoteErrorOf(catchSync(() => controller.start(KEY, 'api-key'))))
      .toMatchObject({ code: 'authorization/rejected' })
  })

  it('refuses a poll, answer, or finish for an unknown attempt', async () => {
    const { controller } = await boot()
    for (const call of [
      () => controller.poll('unknown'),
      () => { controller.answer('unknown', 'v') },
      () => { controller.finish('unknown') },
    ]) {
      expect(remoteErrorOf(catchSync(call))).toMatchObject({ code: 'authorization/rejected' })
    }
  })
})
