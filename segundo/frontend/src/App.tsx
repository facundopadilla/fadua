import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatPanel } from '@/components/ChatPanel'
import { Sidebar } from '@/components/Sidebar'
import { useChatStream } from '@/hooks/useChatStream'
import {
  readConversationMessages,
  useConversations,
  writeConversationMessages,
} from '@/hooks/useConversations'
import { useHealth } from '@/hooks/useHealth'
import { useModels } from '@/hooks/useModels'
import { useSelectedModel } from '@/hooks/useSelectedModel'
import { useTheme } from '@/hooks/useTheme'
import type { ChatMessage } from '@/types/chat'

function makeId() {
  return crypto.randomUUID()
}

/** Replaces the assistant message with the given id, applying `patch` to it. */
function patchAssistantMessage(
  list: ChatMessage[],
  assistantId: string,
  patch: (m: Extract<ChatMessage, { role: 'assistant' }>) => ChatMessage,
): ChatMessage[] {
  return list.map((m) => (m.id === assistantId && m.role === 'assistant' ? patch(m) : m))
}

function App() {
  const { theme, toggleTheme } = useTheme()
  const { data: health } = useHealth()
  const {
    conversations,
    activeId: conversationId,
    setActiveId: setConversationId,
    recordConversation,
    touchConversation,
    deleteConversation,
  } = useConversations()
  const { send, cancel, streamingConversationId } = useChatStream()
  const { models } = useModels()
  const { model: selectedModel, setModel: setSelectedModel } = useSelectedModel(models)

  // The visible transcript for whichever conversation is currently active.
  // Reloaded from localStorage on every switch (see handleSelectConversation
  // / handleNewConversation). Persistence itself is explicit at every
  // mutation site (applyUpdate inside handleSend) rather than a blanket
  // effect here, so a streamed answer is written exactly once per token
  // instead of twice, and so it's obvious persistence and UI state always
  // move together.
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    conversationId ? readConversationMessages(conversationId) : [],
  )
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // A stream is only "blocking" for the conversation it belongs to. If the
  // user has switched away, the same in-flight stream must not disable the
  // input of the newly active (unrelated) conversation.
  const isStreaming = streamingConversationId !== undefined && streamingConversationId === conversationId

  // Lets a send() callback created for an earlier conversation check, later,
  // whether the user has since switched away — without depending on the
  // `conversationId` value captured in its closure at creation time.
  const activeConversationIdRef = useRef(conversationId)
  useEffect(() => {
    activeConversationIdRef.current = conversationId
  }, [conversationId])

  const handleNewConversation = useCallback(() => {
    // Starting fresh always claims the "no id yet" slot; cancel so a stream
    // from a previous new-conversation draft can't race to claim it too.
    cancel()
    setConversationId(null)
    setMessages([])
    setErrorMessage(null)
  }, [cancel, setConversationId])

  const handleSelectConversation = useCallback(
    (id: string) => {
      if (id === conversationId) return
      // Never block switching, and never abort an in-flight stream just for
      // navigating away from it — it keeps running and, when it completes,
      // persists straight to the conversation it belongs to (see handleSend
      // below), even though that conversation is no longer active. We only
      // stop reflecting it in this tab's live state.
      setConversationId(id)
      setMessages(readConversationMessages(id))
      setErrorMessage(null)
    },
    [conversationId, setConversationId],
  )

  const handleDeleteConversation = useCallback(
    (id: string) => {
      const wasActive = id === conversationId
      // Deleting a conversation that's mid-stream: there's no longer a
      // conversation left for that result to belong to, so abort outright.
      if (streamingConversationId === id) cancel()
      deleteConversation(id)
      if (wasActive) {
        setMessages([])
        setErrorMessage(null)
      }
    },
    [cancel, conversationId, deleteConversation, streamingConversationId],
  )

  const handleSend = useCallback(
    (text: string) => {
      // Same conversation already streaming its own reply: normal chat UX,
      // block (mirrors the disabled ChatInput).
      if (streamingConversationId === conversationId) return
      // A DIFFERENT conversation is streaming: only one stream runs at a
      // time, so make room for this one. The old stream is aborted here —
      // deliberately, since the user is actively choosing to chat elsewhere
      // now, not just passively switched away.
      if (streamingConversationId !== undefined) cancel()

      setErrorMessage(null)

      // Bind the conversation this turn belongs to at send-time. The
      // callbacks below always target THIS id for persistence, and only
      // touch live UI state while it's still the active conversation.
      const targetConversationId = conversationId
      const isNewConversation = targetConversationId === null

      const userMessage: ChatMessage = { id: makeId(), role: 'user', content: text }
      const assistantId = makeId()
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        streaming: true,
        response: null,
      }

      // This turn's own running copy of the full message list, threaded
      // through applyUpdate below so onToken/onDone/onError never need to
      // re-derive it from React state (which may belong to a different
      // conversation by the time they fire) or from localStorage (which has
      // nothing yet for a brand new conversation until onDone mints an id).
      let turnMessages: ChatMessage[] = [...messages, userMessage, assistantMessage]

      const isTargetStillActive = () => targetConversationId === activeConversationIdRef.current

      // Reflects `next` in live UI state if the target conversation is still
      // active, and persists it if the target conversation already has a
      // real id (a brand new conversation is persisted separately, once,
      // in onDone below — there's nothing to key it by until then).
      const applyUpdate = (next: ChatMessage[]) => {
        turnMessages = next
        if (isTargetStillActive()) setMessages(next)
        if (targetConversationId !== null) writeConversationMessages(targetConversationId, next)
      }

      applyUpdate(turnMessages)

      void send(text, targetConversationId, selectedModel, {
        onToken: (token) => {
          applyUpdate(
            patchAssistantMessage(turnMessages, assistantId, (m) => ({
              ...m,
              content: m.content + token,
            })),
          )
        },
        onDone: (response) => {
          applyUpdate(
            patchAssistantMessage(turnMessages, assistantId, () => ({
              id: assistantId,
              role: 'assistant',
              content: response.answer,
              streaming: false,
              response,
            })),
          )
          if (isNewConversation) {
            // The backend just minted this conversation's real id. Persist
            // the turn's messages under it, register it in the sidebar, and
            // — only if the user hasn't since started yet another new
            // conversation — activate it.
            writeConversationMessages(response.conversation_id, turnMessages)
            recordConversation(response.conversation_id, text)
            if (activeConversationIdRef.current === null) {
              setConversationId(response.conversation_id)
            }
          } else {
            touchConversation(response.conversation_id)
          }
        },
        onError: (message) => {
          if (isTargetStillActive()) {
            setErrorMessage(`No se pudo obtener respuesta: ${message}`)
          }
          applyUpdate(turnMessages.filter((m) => m.id !== assistantId))
        },
      })
    },
    [
      cancel,
      conversationId,
      messages,
      recordConversation,
      selectedModel,
      send,
      setConversationId,
      streamingConversationId,
      touchConversation,
    ],
  )

  return (
    <div className="flex h-full">
      <Sidebar
        conversations={conversations}
        activeId={conversationId}
        onSelect={handleSelectConversation}
        onNew={handleNewConversation}
        onDelete={handleDeleteConversation}
        theme={theme}
        onToggleTheme={toggleTheme}
        isHealthy={health ? health.status === 'ok' : undefined}
        models={models}
        selectedModel={selectedModel}
        onSelectModel={setSelectedModel}
      />
      <ChatPanel
        messages={messages}
        onSend={handleSend}
        isStreaming={isStreaming}
        errorMessage={errorMessage}
      />
    </div>
  )
}

export default App
