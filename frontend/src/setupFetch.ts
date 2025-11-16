const originalFetch = window.fetch.bind(window)

window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const finalInit: RequestInit = init ? { ...init } : {}
  finalInit.credentials = finalInit.credentials || 'include'

  const token = localStorage.getItem('accessToken')
  if (token) {
    finalInit.headers = {
      ...(finalInit.headers || {}),
      Authorization: `Bearer ${token}`,
    }
  }
  return originalFetch(input, finalInit)
}
