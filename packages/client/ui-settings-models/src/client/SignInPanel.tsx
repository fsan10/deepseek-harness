/**
 * The human-guided sign-in affordance on one provider card.
 *
 * A Web page cannot hold a callback across requests, so the Host projects a
 * flow's notices and questions onto a polled attempt. This panel owns one
 * attempt at a time: it starts it, renders the newest notice (a page to open,
 * a code to enter, or a callback URL to paste back), answers the question the
 * flow asks, and withdraws everything on cancel or unmount.
 */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { AuthorizationAttemptView, AuthorizationFlowView } from '@deepseek-ai/dsh-api-remotes/client'
import type { ModelsOperations } from './operations.ts'
import type { ModelsKey } from './locales.ts'
import styles from './ModelsSection.module.css'

/** Interval between polls of one running attempt. */
const POLL_INTERVAL_MS = 700

export interface SignInPanelProps {
  /** The flow registered for this card's credential key, when one exists. */
  flow: AuthorizationFlowView | undefined
  operations: ModelsOperations
  t: (key: ModelsKey) => string
  readOnly: boolean
  /** Refresh the card's credential state once a record was committed. */
  onAuthorized: () => void
}

/** Render the sign-in state of one provider card. */
export function SignInPanel(props: SignInPanelProps): ReactNode {
  const { flow, operations, t, readOnly, onAuthorized } = props
  const [attemptId, setAttemptId] = useState<string | undefined>(undefined)
  const [view, setView] = useState<AuthorizationAttemptView | undefined>(undefined)
  const [failure, setFailure] = useState<string | undefined>(undefined)
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  // Keep the refresh callback out of the polling effect's dependencies: a
  // parent re-render must not restart a sign-in mid-flow.
  const authorized = useRef(onAuthorized)
  authorized.current = onAuthorized

  useEffect(() => {
    if (attemptId === undefined) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async (): Promise<void> => {
      const result = await operations.pollSignIn(attemptId)
      if (stopped) return
      if (result.kind === 'refused') {
        setFailure(result.message)
        return
      }
      setView(result.value)
      if (result.value.status === 'running') {
        timer = setTimeout(() => { void tick() }, POLL_INTERVAL_MS)
        return
      }
      if (result.value.status === 'authorized') authorized.current()
      await operations.finishSignIn(attemptId)
    }
    void tick()
    return () => {
      stopped = true
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [attemptId, operations])

  // Withdrawing on unmount releases the Host's attempt even when a human
  // navigates away mid-login rather than pressing Cancel.
  useEffect(() => () => {
    if (attemptId !== undefined) void operations.finishSignIn(attemptId)
  }, [attemptId, operations])

  if (flow === undefined) return null

  const start = async (): Promise<void> => {
    setBusy(true)
    setFailure(undefined)
    setView(undefined)
    setAnswer('')
    const result = await operations.startSignIn(flow.key, flow.methods[0]?.id)
    setBusy(false)
    if (result.kind === 'refused') setFailure(result.message)
    else setAttemptId(result.value)
  }

  const submit = async (): Promise<void> => {
    if (attemptId === undefined) return
    setFailure(await operations.answerSignIn(attemptId, answer))
    setAnswer('')
  }

  const withdraw = async (): Promise<void> => {
    await operations.cancelSignIn(flow.key)
    if (attemptId !== undefined) await operations.finishSignIn(attemptId)
    setAttemptId(undefined)
    setView(undefined)
    setFailure(undefined)
  }

  const close = (): void => {
    setAttemptId(undefined)
    setView(undefined)
    setFailure(undefined)
    setAnswer('')
  }

  const running = attemptId !== undefined && view?.status !== 'authorized'
    && view?.status !== 'cancelled' && view?.status !== 'failed'
  const latest = view?.notices[view.notices.length - 1]
  const prompt = view?.prompt

  return (
    <div className={styles['field']}>
      {latest !== undefined && <p className={styles['advancedHint']}>{latest.message}</p>}
      {latest?.code !== undefined && <>
        <span className={styles['fieldLabel']}>{t('signInCode')}</span>
        <code className={styles['candidateId']}>{latest.code}</code>
      </>}
      {latest?.url !== undefined && <>
        <a className={styles['linkButton']} href={latest.url} target="_blank" rel="noreferrer">
          {t('signInOpenLink')}
        </a>
        <code className={styles['candidateId']}>{latest.url}</code>
      </>}
      {running && latest === undefined && <p className={styles['advancedHint']}>{t('signInWaiting')}</p>}
      {running && prompt !== undefined && (
        <div className={styles['field']}>
          <span className={styles['fieldLabel']}>{prompt.message}</span>
          {prompt.kind === 'select'
            ? (
              <select
                className={styles['selectInput']}
                value={answer}
                onChange={(event) => { setAnswer(event.target.value) }}
                aria-label={t('signInValue')}
              >
                <option value="">{t('signInSelect')}</option>
                {prompt.options.map(option => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </select>
            )
            : (
              <input
                className={styles['input']}
                type={prompt.kind === 'secret' ? 'password' : 'text'}
                value={answer}
                onChange={(event) => { setAnswer(event.target.value) }}
                placeholder={prompt.placeholder}
                aria-label={t('signInValue')}
                autoComplete="off"
              />
            )}
          <button
            className={styles['primaryButton']}
            disabled={answer.length === 0}
            onClick={() => { void submit() }}
          >
            {t('signInSubmit')}
          </button>
        </div>
      )}
      {view?.status === 'authorized' && <p className={styles['notice']}>{t('signInAuthorized')}</p>}
      {view?.status === 'cancelled' && <p className={styles['notice']}>{t('signInCancelled')}</p>}
      {view?.status === 'failed' && <p className={styles['error']}>{view.error ?? t('signInFailed')}</p>}
      {failure !== undefined && <p className={styles['error']}>{failure}</p>}
      <div className={styles['editorActions']}>
        {attemptId === undefined
          ? (
            <button
              className={styles['secondaryButton']}
              disabled={readOnly || busy || flow.inFlight}
              onClick={() => { void start() }}
            >
              {busy ? t('signInBusy') : flow.methods[0]?.label ?? t('signIn')}
            </button>
          )
          : running
            ? (
              <button className={styles['secondaryButton']} onClick={() => { void withdraw() }}>
                {t('signInCancel')}
              </button>
            )
            : (
              <button className={styles['secondaryButton']} onClick={close}>
                {t('signInDone')}
              </button>
            )}
      </div>
    </div>
  )
}
