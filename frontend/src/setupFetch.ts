const originalFetch = window.fetch.bind(window)

window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const finalInit: RequestInit = init ? { ...init } : {}
  if (!finalInit.credentials) {
    finalInit.credentials = 'include'
  }
  return originalFetch(input, finalInit)
}

