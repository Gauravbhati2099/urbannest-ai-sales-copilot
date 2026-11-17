import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  Bot,
  Check,
  CircleAlert,
  LoaderCircle,
  MessageSquareText,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
  UserRound,
} from 'lucide-react'
import {
  ApiError,
  api,
  type ChatConversation,
  type ChatMessage,
  type ChatSendResponse,
} from './api'
import './ChatPage.css'

type ChatPageProps = {
  token: string
  onUnauthorized: () => void
}

const toolLabels: Record<string, string> = {
  search_leads: 'Searched leads',
  get_lead_summary: 'Read lead summary',
  list_tasks: 'Listed follow-ups',
  search_estates: 'Searched estates',
  get_estate_details: 'Read estate details',
}

function messageTime(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(timestamp))
}

function conversationTime(timestamp: string) {
  const date = new Date(timestamp)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) return messageTime(timestamp)
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
  }).format(date)
}

export function ChatPage({ token, onUnauthorized }: ChatPageProps) {
  const [conversations, setConversations] = useState<ChatConversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [loadingConversations, setLoadingConversations] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [deletePending, setDeletePending] = useState(false)
  const messageEndRef = useRef<HTMLDivElement>(null)

  const loadConversations = useCallback(async () => {
    setLoadingConversations(true)
    setError('')
    try {
      const result = await api<ChatConversation[]>('/chat/conversations', token)
      setConversations(result)
      setSelectedConversationId((current) => (
        current && result.some((conversation) => conversation.id === current)
          ? current
          : result[0]?.id ?? null
      ))
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized()
        return
      }
      setError(requestError instanceof Error ? requestError.message : 'Could not load chat history.')
    } finally {
      setLoadingConversations(false)
    }
  }, [onUnauthorized, token])

  const loadMessages = useCallback(async (conversationId: string) => {
    setLoadingMessages(true)
    setError('')
    try {
      const result = await api<ChatMessage[]>(
        `/chat/conversations/${encodeURIComponent(conversationId)}/messages`,
        token,
      )
      setMessages(result)
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized()
        return
      }
      setMessages([])
      setError(requestError instanceof Error ? requestError.message : 'Could not load this conversation.')
    } finally {
      setLoadingMessages(false)
    }
  }, [onUnauthorized, token])

  useEffect(() => {
    // eslint-disable-next-line react/set-state-in-effect -- Loads the server-owned conversation list.
    void loadConversations()
  }, [loadConversations])

  useEffect(() => {
    if (selectedConversationId) {
      // eslint-disable-next-line react/set-state-in-effect -- Loads history for the selected conversation.
      void loadMessages(selectedConversationId)
    }
  }, [loadMessages, selectedConversationId])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  const startNewConversation = () => {
    setSelectedConversationId(null)
    setMessages([])
    setDraft('')
    setError('')
  }

  const sendMessage = async (event?: FormEvent) => {
    event?.preventDefault()
    const message = draft.trim()
    if (!message || sending) return

    setSending(true)
    setError('')
    setDraft('')
    const pendingMessage: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
      tool_executions: [],
    }
    setMessages((current) => [...current, pendingMessage])

    try {
      const result = await api<ChatSendResponse>('/chat/messages', token, {
        method: 'POST',
        body: JSON.stringify({
          message,
          conversation_id: selectedConversationId,
        }),
      })
      const sentAt = new Date().toISOString()
      setSelectedConversationId(result.conversation_id)
      setMessages((current) => [
        ...current.filter((item) => item.id !== pendingMessage.id),
        { ...pendingMessage, id: `sent-user-${crypto.randomUUID()}` },
        {
          id: `sent-assistant-${crypto.randomUUID()}`,
          role: 'assistant',
          content: result.response,
          created_at: sentAt,
          tool_executions: result.tool_executions,
        },
      ])
      void loadConversations()
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized()
        return
      }
      setMessages((current) => current.filter((item) => item.id !== pendingMessage.id))
      setDraft(message)
      setError(requestError instanceof Error ? requestError.message : 'Your message could not be sent.')
    } finally {
      setSending(false)
    }
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  const deleteConversation = async () => {
    if (!selectedConversationId || sending || deletePending) return
    if (!window.confirm('Delete this conversation and its saved messages?')) return
    setDeletePending(true)
    setError('')
    try {
      await api<void>(
        `/chat/conversations/${encodeURIComponent(selectedConversationId)}`,
        token,
        { method: 'DELETE' },
      )
      setSelectedConversationId(null)
      setMessages([])
      setConversations((current) => current.filter(
        (conversation) => conversation.id !== selectedConversationId,
      ))
      void loadConversations()
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized()
        return
      }
      setError(requestError instanceof Error ? requestError.message : 'Could not delete this conversation.')
    } finally {
      setDeletePending(false)
    }
  }

  const selectedConversation = conversations.find(
    (conversation) => conversation.id === selectedConversationId,
  )
  const visibleMessages = selectedConversationId || sending ? messages : []

  return (
    <section className="chat-workspace" aria-label="AI chat">
      <aside className="chat-history panel" aria-label="Conversation history">
        <div className="chat-history-header">
          <div>
            <p className="eyebrow">PRIVATE HISTORY</p>
            <h2>Conversations</h2>
          </div>
          <button
            className="chat-icon-button"
            type="button"
            onClick={() => void loadConversations()}
            disabled={loadingConversations || sending}
            aria-label="Refresh conversations"
            title="Refresh conversations"
          >
            <RefreshCw size={16} className={loadingConversations ? 'spinning' : ''} />
          </button>
        </div>
        <button className="chat-new-button" type="button" onClick={startNewConversation} disabled={sending || loadingMessages}>
          <Plus size={16} />
          New conversation
        </button>
        <div className="chat-history-list">
          {loadingConversations && conversations.length === 0 ? (
            <p className="chat-history-note">Loading conversations…</p>
          ) : conversations.length === 0 ? (
            <p className="chat-history-note">Your saved conversations will appear here.</p>
          ) : conversations.map((conversation) => (
            <button
              className={`chat-history-item ${conversation.id === selectedConversationId ? 'chat-history-item-active' : ''}`}
              type="button"
              key={conversation.id}
              onClick={() => setSelectedConversationId(conversation.id)}
              disabled={sending || loadingMessages}
              aria-current={conversation.id === selectedConversationId ? 'page' : undefined}
            >
              <MessageSquareText size={15} />
              <span className="chat-history-copy">
                <strong>{conversation.title}</strong>
                <small>{conversationTime(conversation.updated_at)}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="chat-retention-note">
          <ShieldCheck size={15} />
          <span>Only you can see your history. Chats are automatically removed after 30 days.</span>
        </div>
      </aside>

      <div className="chat-panel panel">
        <header className="chat-panel-header">
          <div className="chat-assistant-mark"><Bot size={19} /></div>
          <div className="chat-panel-title">
            <strong>{selectedConversation?.title ?? 'UrbanNest assistant'}</strong>
            <span><i /> Connected to your authorized CRM data</span>
          </div>
          {selectedConversationId && (
            <button
              className="chat-icon-button chat-delete-button"
              type="button"
              onClick={() => void deleteConversation()}
              disabled={deletePending || sending}
              aria-label="Delete conversation"
              title="Delete conversation"
            >
              {deletePending ? <LoaderCircle size={16} className="spinning" /> : <Trash2 size={16} />}
            </button>
          )}
        </header>

        <div className="chat-message-list" aria-live="polite">
          {loadingMessages ? (
            <div className="chat-empty-state"><LoaderCircle size={21} className="spinning" />Loading conversation…</div>
          ) : visibleMessages.length === 0 ? (
            <div className="chat-empty-state">
              <span className="chat-empty-icon"><MessageSquareText size={23} /></span>
              <h3>How can I help with your CRM?</h3>
              <p>Ask about leads, follow-ups, or estate inventory you’re authorized to see.</p>
              <div className="chat-suggestions">
                {['Show my open follow-ups', 'Find available estates', 'Summarize my recent leads'].map((suggestion) => (
                  <button type="button" key={suggestion} onClick={() => setDraft(suggestion)}>
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : visibleMessages.map((message) => (
            <article className={`chat-message chat-message-${message.role}`} key={message.id}>
              <span className={`chat-message-avatar chat-message-avatar-${message.role}`}>
                {message.role === 'assistant' ? <Bot size={16} /> : <UserRound size={15} />}
              </span>
              <div className="chat-message-content">
                <div className="chat-message-meta">
                  <strong>{message.role === 'assistant' ? 'UrbanNest assistant' : 'You'}</strong>
                  <time dateTime={message.created_at}>{messageTime(message.created_at)}</time>
                </div>
                <p>{message.content}</p>
                {message.tool_executions.length > 0 && (
                  <div className="chat-tool-status" aria-label="Tool execution status">
                    {message.tool_executions.map((tool, index) => (
                      <span className={`chat-tool-status-item chat-tool-${tool.status}`} key={`${tool.name}-${index}`}>
                        {tool.status === 'succeeded' ? <Check size={13} /> : <CircleAlert size={13} />}
                        {toolLabels[tool.name] ?? 'CRM tool'}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </article>
          ))}
          {sending && (
            <div className="chat-working" role="status">
              <LoaderCircle size={15} className="spinning" />
              Checking your authorized CRM data…
            </div>
          )}
          <div ref={messageEndRef} />
        </div>

        {error && <div className="chat-error" role="alert"><CircleAlert size={15} />{error}</div>}
        <form className="chat-composer" onSubmit={(event) => void sendMessage(event)}>
          <label className="visually-hidden" htmlFor="chat-message">Message the UrbanNest assistant</label>
          <textarea
            id="chat-message"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Ask a question about your CRM…"
            maxLength={4000}
            rows={2}
            disabled={sending}
          />
          <div className="chat-composer-footer">
            <span>Enter to send · Shift + Enter for a new line</span>
            <button
              className="chat-send-button"
              type="submit"
              disabled={!draft.trim() || sending}
              aria-label="Send message"
              title="Send message"
            >
              {sending ? <LoaderCircle size={16} className="spinning" /> : <Send size={16} />}
            </button>
          </div>
        </form>
      </div>
    </section>
  )
}
