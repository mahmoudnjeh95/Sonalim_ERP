import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import {
  ACTIVE_CONSOLIDATIONS_QUERY_KEY,
  cancelWorkOrder,
  closeWorkOrder,
  resumeWorkOrder,
  startWorkOrder,
  suspendWorkOrder,
  updateWorkOrder,
  type UpdateWorkOrderInput,
} from "./api";

/** The work-order list and its overview both sit under this prefix, so one invalidation refreshes both. */
export const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;

/**
 * Every change an OF's row or dialogs can make. The OF lifecycle posts no stock: what was produced and
 * consumed is recorded on the OF's shifts and posted when a supervisor validates them.
 */
export function useWorkOrderActions(token: string, callbacks: { onUpdated?: () => void; onClosed?: () => void } = {}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: WORK_ORDERS_QUERY_KEY });
    // Start, suspend and close change which orders the cockpit counts as active.
    queryClient.invalidateQueries({ queryKey: ACTIVE_CONSOLIDATIONS_QUERY_KEY });
  };
  const failed = (errorKey: string) => (error: unknown) =>
    toast.error(t(errorKey as TranslationKey), { description: error instanceof ApiError ? error.message : undefined });

  const lifecycle = (action: (id: string) => Promise<unknown>, successKey: string, errorKey: string) => ({
    mutationFn: (id: string) => action(id),
    onSuccess: () => {
      refresh();
      toast.success(t(successKey as TranslationKey));
    },
    onError: failed(errorKey),
  });

  const start = useMutation(lifecycle((id) => startWorkOrder(token, id), "production.workOrders.started", "production.workOrders.startError"));
  const suspend = useMutation(
    lifecycle((id) => suspendWorkOrder(token, id), "production.workOrders.suspendedToast", "production.workOrders.suspendError"),
  );
  const resume = useMutation(
    lifecycle((id) => resumeWorkOrder(token, id), "production.workOrders.resumedToast", "production.workOrders.resumeError"),
  );
  const cancel = useMutation(
    lifecycle((id) => cancelWorkOrder(token, id), "production.workOrders.cancelledToast", "production.workOrders.cancelError"),
  );

  // Closing asks when the order actually finished (defaults to now, adjustable), so a shift wrapped up
  // and closed the next morning can record the real time.
  const close = useMutation({
    mutationFn: ({ id, closedAt }: { id: string; closedAt: string }) => closeWorkOrder(token, id, crypto.randomUUID(), { closedAt }),
    onSuccess: () => {
      refresh();
      callbacks.onClosed?.();
      toast.success(t("production.workOrders.closedToast"));
    },
    onError: failed("production.workOrders.closeError"),
  });

  const update = useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateWorkOrderInput }) => updateWorkOrder(token, id, input),
    onSuccess: () => {
      refresh();
      callbacks.onUpdated?.();
      toast.success(t("production.workOrders.updated"));
    },
    onError: failed("production.workOrders.updateError"),
  });

  return { start, suspend, resume, cancel, close, update, refresh };
}
