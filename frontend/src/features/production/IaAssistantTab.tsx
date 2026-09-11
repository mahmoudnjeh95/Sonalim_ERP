import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Loader2, MessageSquarePlus, Send, Sparkles, Trash2 } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Card, CardContent } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/patterns/EmptyState";
import { cn } from "../../lib/utils";
import {
  createIaAssistantConversation,
  deleteIaAssistantConversation,
  listIaAssistantConversations,
  listIaAssistantMessages,
  sendIaAssistantMessage,
  type IaAssistantConversation,
} from "./api";

const CONVERSATIONS_QUERY_KEY = ["production", "ia-assistant", "conversations"] as const;

function conversationLabel(conversation: IaAssistantConversation): string {
  return conversation.title || new Date(conversation.updated_at).toLocaleString();
}

export function IaAssistantTab() {
  const { t, language } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canUse = hasPermission("production.use_ia_assistant");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [errorKey, setErrorKey] = useState<"rateLimited" | "unavailable" | "generic" | null>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

  const { data: conversations = [], isLoading: loadingConversations } = useQuery({
    queryKey: CONVERSATIONS_QUERY_KEY,
    queryFn: () => listIaAssistantConversations(token),
    enabled: canUse,
  });

  // Land on the most recently active conversation once the list is in, rather
  // than forcing every visit to start blank.
  useEffect(() => {
    if (selectedId === null && conversations.length > 0) {
      setSelectedId(conversations[0].id);
    }
  }, [conversations, selectedId]);

  const { data: messages = [], isLoading: loadingMessages } = useQuery({
    queryKey: ["production", "ia-assistant", "messages", selectedId],
    queryFn: () => listIaAssistantMessages(token, selectedId!),
    enabled: canUse && selectedId !== null,
  });

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const createMutation = useMutation({
    mutationFn: () => createIaAssistantConversation(token),
    onSuccess: (conversation) => {
      queryClient.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
      setSelectedId(conversation.id);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (conversationId: string) => deleteIaAssistantConversation(token, conversationId),
    onSuccess: (_data, conversationId) => {
      queryClient.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
      if (selectedId === conversationId) setSelectedId(null);
    },
  });

  // Takes the target conversation id explicitly rather than reading `selectedId`
  // from closure -- starting a brand-new conversation sets the id and sends the
  // first message in the same gesture, before a re-render could ever land that
  // state, so a closure here would silently target the previous (often null)
  // conversation.
  const sendMutation = useMutation({
    mutationFn: ({ conversationId, content }: { conversationId: string; content: string }) =>
      sendIaAssistantMessage(token, conversationId, content, language),
    onMutate: () => setErrorKey(null),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["production", "ia-assistant", "messages", variables.conversationId] });
      queryClient.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
      setDraft("");
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 429) setErrorKey("rateLimited");
      else if (error instanceof ApiError && error.status === 503) setErrorKey("unavailable");
      else setErrorKey("generic");
    },
  });

  if (!canUse) {
    return (
      <div className="space-y-6">
        <PageHeader t={t} />
        <EmptyState
          icon={<Sparkles className="h-5 w-5" />}
          title={t("production.iaAssistant.noPermission.title")}
          description={t("production.iaAssistant.noPermission.description")}
        />
      </div>
    );
  }

  async function handleNewConversation() {
    await createMutation.mutateAsync();
  }

  function handleSend(content: string) {
    const trimmed = content.trim();
    if (!trimmed || sendMutation.isPending) return;
    if (selectedId === null) {
      createMutation.mutate(undefined, {
        onSuccess: (conversation) => {
          setSelectedId(conversation.id);
          sendMutation.mutate({ conversationId: conversation.id, content: trimmed });
        },
      });
      return;
    }
    sendMutation.mutate({ conversationId: selectedId, content: trimmed });
  }

  return (
    <div className="space-y-6">
      <PageHeader t={t} />
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="h-fit">
        <CardContent className="space-y-2 p-3">
          <Button variant="outline" size="sm" className="w-full justify-start" onClick={handleNewConversation} disabled={createMutation.isPending}>
            <MessageSquarePlus className="h-3.5 w-3.5" />
            {t("production.iaAssistant.newConversation")}
          </Button>

          {loadingConversations ? (
            <div className="space-y-2 pt-1">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">{t("production.iaAssistant.noConversations")}</p>
          ) : (
            <ul className="space-y-1 pt-1">
              {conversations.map((conversation) => (
                <li key={conversation.id} className="group flex items-center gap-1">
                  <button
                    onClick={() => setSelectedId(conversation.id)}
                    className={cn(
                      "flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                      selectedId === conversation.id ? "bg-primary/10 text-primary" : "hover:bg-muted",
                    )}
                    title={conversationLabel(conversation)}
                  >
                    {conversationLabel(conversation)}
                  </button>
                  <button
                    onClick={() => deleteMutation.mutate(conversation.id)}
                    className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                    aria-label={t("production.iaAssistant.deleteConversation")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="flex h-[600px] flex-col">
        <CardContent className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
          <p className="text-xs text-muted-foreground">{t("production.iaAssistant.scopeHint")}</p>

          <div className="flex-1 overflow-y-auto rounded-md border border-border/60 bg-muted/20 p-3">
            {selectedId === null ? (
              <EmptyState
                icon={<Sparkles className="h-5 w-5" />}
                title={t("production.iaAssistant.empty.title")}
                description={t("production.iaAssistant.empty.description")}
                action={
                  <Button size="sm" onClick={() => handleSend(t("production.iaAssistant.suggestPrompt"))}>
                    <Sparkles className="h-3.5 w-3.5" />
                    {t("production.iaAssistant.suggestAction")}
                  </Button>
                }
              />
            ) : loadingMessages ? (
              <div className="space-y-3">
                <Skeleton className="h-10 w-2/3" />
                <Skeleton className="ml-auto h-10 w-1/2" />
              </div>
            ) : messages.length === 0 ? (
              <EmptyState
                icon={<Sparkles className="h-5 w-5" />}
                title={t("production.iaAssistant.empty.title")}
                description={t("production.iaAssistant.empty.description")}
                action={
                  <Button size="sm" onClick={() => handleSend(t("production.iaAssistant.suggestPrompt"))}>
                    <Sparkles className="h-3.5 w-3.5" />
                    {t("production.iaAssistant.suggestAction")}
                  </Button>
                }
              />
            ) : (
              <div className="space-y-3">
                {messages.map((message) => (
                  <div key={message.id} className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}>
                    <div
                      className={cn(
                        "max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
                        message.role === "user" ? "bg-primary text-primary-foreground" : "bg-background shadow-soft",
                      )}
                    >
                      {message.content}
                    </div>
                  </div>
                ))}
                {sendMutation.isPending && (
                  <div className="flex justify-start">
                    <div className="flex items-center gap-2 rounded-lg bg-background px-3 py-2 text-sm text-muted-foreground shadow-soft">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      {t("production.iaAssistant.thinking")}
                    </div>
                  </div>
                )}
                <div ref={threadEndRef} />
              </div>
            )}
          </div>

          {errorKey && (
            <p className="text-sm text-destructive">
              {t(
                errorKey === "rateLimited"
                  ? "production.iaAssistant.error.rateLimited"
                  : errorKey === "unavailable"
                    ? "production.iaAssistant.error.unavailable"
                    : "production.iaAssistant.error.generic",
              )}
            </p>
          )}

          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              handleSend(draft);
            }}
          >
            <Input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t("production.iaAssistant.placeholder")}
              disabled={sendMutation.isPending}
            />
            <Button type="submit" size="default" disabled={sendMutation.isPending || draft.trim().length === 0}>
              {sendMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </form>
        </CardContent>
      </Card>
      </motion.div>
    </div>
  );
}

function PageHeader({ t }: { t: (key: TranslationKey) => string }) {
  return (
    <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
      <h1 className="text-xl font-semibold tracking-tight">{t("production.iaAssistant.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("production.iaAssistant.subtitle")}</p>
    </motion.div>
  );
}
