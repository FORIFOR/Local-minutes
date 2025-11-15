export function isRecordingActive(): boolean {
  try {
    return sessionStorage.getItem('recordingActive') === '1'
  } catch {
    return false
  }
}

export function navigateApp(path: string, { replace = false }: { replace?: boolean } = {}) {
  if (isRecordingActive()) {
    window.open(path, '_blank', 'noopener,noreferrer')
    return
  }
  if (replace) {
    window.location.replace(path)
  } else {
    window.location.assign(path)
  }
}
