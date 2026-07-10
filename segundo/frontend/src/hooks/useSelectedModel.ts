import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'fadua.model'
const DEFAULT_MODEL = 'deepseek-v4-pro'

function readStorage(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStorage(model: string) {
  try {
    localStorage.setItem(STORAGE_KEY, model)
  } catch {
    // localStorage unavailable — selection just won't persist across reloads.
  }
}

/**
 * Persists the selected model id in localStorage. Defaults to
 * deepseek-v4-pro, falling back to the first available model once the list
 * of available models is known (in case the stored/default id no longer
 * exists on the backend).
 */
export function useSelectedModel(availableModels: string[]) {
  const [model, setModelState] = useState<string>(() => readStorage() ?? DEFAULT_MODEL)

  useEffect(() => {
    if (availableModels.length === 0) return
    if (availableModels.includes(model)) return
    setModelState(availableModels[0])
  }, [availableModels, model])

  const setModel = useCallback((next: string) => {
    setModelState(next)
    writeStorage(next)
  }, [])

  return { model, setModel }
}
