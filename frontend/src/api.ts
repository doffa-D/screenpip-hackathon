export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
export async function api<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), path.startsWith('/chat/') ? 310000 : body === undefined ? 15000 : 270000)
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      ...(body === undefined ? {} : {method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)}),
    })
    if (response.status === 204) return undefined as T
    const data = await response.json()
    if (!response.ok) throw new ApiError(response.status, typeof data.detail === 'string' ? data.detail : 'The request could not be completed.')
    return data as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if ((error as Error).name === 'AbortError') throw new Error('The request timed out. Check the connection and try again. Check Runs or Record before repeating a change.')
    throw new Error('Melon lost its local connection. Reopen the Melon desktop app, then try again. Check Runs or Record before repeating a change.')
  } finally { clearTimeout(timeout) }
}
