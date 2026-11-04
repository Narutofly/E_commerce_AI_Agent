export interface User { id: string; username: string; role: 'customer' | 'merchant' }
export interface Order { id: string; product: string; amount: number; signed_at: string; logistics: string }
export interface Policy { id: string; title: string; body: string; version: number; created_at?: string }
export interface Ticket { id: string; order_id: string; kind: string; reason: string; status: string; opinion: string; created_at: string; snapshot: Policy[]; precheck: { result: string; rule_days: number; elapsed_days: number } }
export interface ChatMessage { role: string; content: string; mode: string }
export interface Conversation { id: string; order_id: string | null; created_at?: string; messages?: ChatMessage[] }
export interface Audit { id: number; actor: string; action: string; target: string; detail: string; created_at: string }
export async function api<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch('/api/sales' + path, { method, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (sessionStorage.getItem('sales-token') || '') }, body: data === undefined ? undefined : JSON.stringify(data) })
  const body = await response.json()
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('sales-expired'))
    throw new Error(typeof body.detail === 'string' ? body.detail : '输入有误，请检查表单后重试')
  }
  return body
}
