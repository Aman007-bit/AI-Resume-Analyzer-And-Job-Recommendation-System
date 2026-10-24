import { useEffect, useState } from 'react'

const UNSET = Symbol('unset')

/**
 * Calls an async service function and tracks loading / error / data.
 *   const { data, loading, error } = useAsyncData(getJobById, id)
 * The fetcher must be a stable reference (a module-level service function).
 * Re-runs whenever `arg` changes.
 */
export default function useAsyncData(fetcher, arg) {
  const [state, setState] = useState({ settledFor: UNSET, data: null, error: null })

  useEffect(() => {
    let cancelled = false
    fetcher(arg)
      .then((data) => {
        if (!cancelled) setState({ settledFor: arg, data, error: null })
      })
      .catch((error) => {
        if (!cancelled) setState({ settledFor: arg, data: null, error })
      })
    return () => {
      cancelled = true
    }
  }, [fetcher, arg])

  const loading = !Object.is(state.settledFor, arg)
  return {
    loading,
    data: loading ? null : state.data,
    error: loading ? null : state.error,
  }
}
