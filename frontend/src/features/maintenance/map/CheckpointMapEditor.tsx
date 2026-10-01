import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, Camera, ImagePlus, Pencil, Trash2 } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../../../components/ui/dialog";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import {
  fetchViewImageBlob,
  useArchiveCheckpoint,
  useCreateCheckpoint,
  useCreateEquipmentView,
  useDeleteEquipmentView,
  useEquipmentViews,
  useUpdateCheckpoint,
  useUpdateEquipmentView,
  type Checkpoint,
  type EquipmentView,
} from "../api";
import { useAuthedImage } from "../useAuthedImage";
import { shrinkImageToFile } from "./shrinkImageFile";
import { PinnedPhoto, type Pin } from "./PinnedPhoto";
import { CheckpointForm } from "./CheckpointForm";

/** The label+image dialog shared by "Ajouter une vue" and "Remplacer la photo". */
function ViewFormDialog({
  open,
  onOpenChange,
  initialLabel,
  requireImage,
  isSaving,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialLabel: string;
  /** true for a new view (image mandatory); false for "replace photo" where the label can be edited alone. */
  requireImage: boolean;
  isSaving: boolean;
  onSubmit: (values: { label: string; image: File | null }) => void;
}) {
  const { t } = useI18n();
  const [label, setLabel] = useState(initialLabel);
  const [file, setFile] = useState<File | null>(null);
  const [preparing, setPreparing] = useState(false);

  useEffect(() => {
    if (open) {
      setLabel(initialLabel);
      setFile(null);
    }
  }, [open, initialLabel]);

  async function handleFileChange(selected: File | null) {
    if (!selected) {
      setFile(null);
      return;
    }
    setPreparing(true);
    try {
      setFile(await shrinkImageToFile(selected));
    } catch {
      toast.error(t("maintenance.map.view.imageError"));
      setFile(null);
    } finally {
      setPreparing(false);
    }
  }

  const canSubmit = label.trim().length > 0 && (!requireImage || !!file) && !preparing;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{requireImage ? t("maintenance.map.view.addTitle") : t("maintenance.map.view.replaceTitle")}</DialogTitle>
          <DialogDescription>
            {requireImage ? t("maintenance.map.view.addDescription") : t("maintenance.map.view.replaceDescription")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            onSubmit({ label: label.trim(), image: file });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="view-label">{t("maintenance.map.view.field.label")}</Label>
            <Input
              id="view-label"
              autoFocus
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder={t("maintenance.map.view.field.label.placeholder")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="view-image">{t("maintenance.map.view.field.image")}</Label>
            <Input
              id="view-image"
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
            />
            {preparing && <p className="text-xs text-muted-foreground">{t("maintenance.map.view.preparingImage")}</p>}
            {file && !preparing && <p className="text-xs text-success">{t("maintenance.map.view.imageReady")}</p>}
          </div>
          <Button type="submit" className="w-full" disabled={!canSubmit || isSaving}>
            {isSaving ? t("maintenance.map.view.saving") : t("maintenance.map.view.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ViewPhoto({ view, pins, onPick, onPinClick, onPinMoveEnd }: {
  view: EquipmentView;
  pins: Pin[];
  onPick?: (x: number, y: number) => void;
  onPinClick?: (id: string) => void;
  onPinMoveEnd?: (id: string, x: number, y: number) => void;
}) {
  const { url, isLoading } = useAuthedImage(fetchViewImageBlob, view.id, view.updated_at);
  const { t } = useI18n();
  if (isLoading || !url) {
    return (
      <div className="flex aspect-[4/3] w-full items-center justify-center rounded-lg bg-muted">
        <AppLoader size={96} label={t("maintenance.map.view.loadingPhoto")} />
      </div>
    );
  }
  return <PinnedPhoto src={url} pins={pins} onPick={onPick} onPinClick={onPinClick} onPinMoveEnd={onPinMoveEnd} />;
}

/**
 * Task F3: machine checkpoint-map editor. One tab per equipment view (photo);
 * the active view's photo is shown with its checkpoints as draggable numbered
 * pins. "Add point" mode: tap the photo to drop a new pin and open the side
 * form; clicking an existing pin (outside add mode) opens it for editing;
 * dragging a pin PATCHes its position on drop.
 */
export function CheckpointMapEditor() {
  const { equipmentId } = useParams<{ equipmentId: string }>();
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const { data: views = [], isLoading } = useEquipmentViews(token, equipmentId ?? null);
  const [activeViewId, setActiveViewId] = useState<string | null>(null);
  const [addMode, setAddMode] = useState(false);
  const [pendingPosition, setPendingPosition] = useState<{ x: number; y: number } | null>(null);
  const [selectedCheckpointId, setSelectedCheckpointId] = useState<string | null>(null);
  const [addViewOpen, setAddViewOpen] = useState(false);
  const [replaceViewOpen, setReplaceViewOpen] = useState(false);
  // Optimistic position shown for a checkpoint while its PATCH (fired once, on
  // drop) is in flight — cleared on success (the refetched checkpoint already
  // has the new x_pct/y_pct by then) or on failure (rolls back to the
  // server's last-known position, which `checkpoint.x_pct/y_pct` still is).
  const [optimisticPositions, setOptimisticPositions] = useState<Record<string, { x: number; y: number }>>({});

  useEffect(() => {
    if (views.length > 0 && !views.some((v) => v.id === activeViewId)) {
      setActiveViewId(views[0].id);
    }
    if (views.length === 0) setActiveViewId(null);
  }, [views, activeViewId]);

  const activeView = views.find((v) => v.id === activeViewId) ?? null;
  const visibleCheckpoints = activeView?.checkpoints.filter((c) => !c.archived_at) ?? [];
  const selectedCheckpoint = visibleCheckpoints.find((c) => c.id === selectedCheckpointId) ?? null;

  const createView = useCreateEquipmentView(token);
  const updateView = useUpdateEquipmentView(token);
  const deleteView = useDeleteEquipmentView(token);
  const createCheckpoint = useCreateCheckpoint(token);
  const updateCheckpoint = useUpdateCheckpoint(token);
  const archiveCheckpoint = useArchiveCheckpoint(token);

  function closeForm() {
    setPendingPosition(null);
    setSelectedCheckpointId(null);
  }

  function handlePick(x: number, y: number) {
    if (!addMode) return;
    setSelectedCheckpointId(null);
    setPendingPosition({ x, y });
  }

  function handlePinClick(id: string) {
    if (addMode) return;
    setPendingPosition(null);
    setSelectedCheckpointId(id);
  }

  function handlePinMoveEnd(id: string, x: number, y: number) {
    if (!activeView) return;
    // Optimistic: the pin stays at the dropped spot immediately; roll back to
    // the server position only if the PATCH actually fails.
    setOptimisticPositions((prev) => ({ ...prev, [id]: { x, y } }));
    updateCheckpoint.mutate(
      { checkpointId: id, input: { x_pct: x, y_pct: y } },
      {
        onSuccess: () => {
          setOptimisticPositions((prev) => {
            const { [id]: _removed, ...rest } = prev;
            return rest;
          });
        },
        onError: (error) => {
          setOptimisticPositions((prev) => {
            const { [id]: _removed, ...rest } = prev;
            return rest;
          });
          toast.error(t("maintenance.map.point.moveError"), { description: error instanceof ApiError ? error.message : undefined });
        },
      },
    );
  }

  const pins: Pin[] = visibleCheckpoints
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((checkpoint, index) => {
      const optimistic = optimisticPositions[checkpoint.id];
      return {
        id: checkpoint.id,
        x: optimistic?.x ?? checkpoint.x_pct,
        y: optimistic?.y ?? checkpoint.y_pct,
        n: index + 1,
        tone: checkpoint.id === selectedCheckpointId ? "active" : "default",
      };
    });
  if (pendingPosition) {
    pins.push({ id: "__pending__", x: pendingPosition.x, y: pendingPosition.y, n: pins.length + 1, tone: "active" });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button asChild variant="outline" size="sm">
          <Link to="/maintenance?tab=equipment">
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("maintenance.map.back")}
          </Link>
        </Button>
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{t("maintenance.map.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("maintenance.map.subtitle")}</p>
        </div>
      </div>

      {isLoading && (
        <div className="py-16">
          <AppLoader label={t("app.loading")} />
        </div>
      )}

      {!isLoading && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {views.map((view) => (
              <Button
                key={view.id}
                size="sm"
                variant={view.id === activeViewId ? "default" : "outline"}
                onClick={() => {
                  setActiveViewId(view.id);
                  closeForm();
                  setAddMode(false);
                }}
              >
                {view.label}
                <span className="ml-1 text-xs opacity-75">({view.checkpoints.filter((c) => !c.archived_at).length})</span>
              </Button>
            ))}
            <Button size="sm" variant="outline" onClick={() => setAddViewOpen(true)}>
              <ImagePlus className="h-3.5 w-3.5" />
              {t("maintenance.map.view.add")}
            </Button>
          </div>

          {!activeView && views.length === 0 && (
            <Card>
              <CardContent className="p-0">
                <EmptyState
                  icon={<Camera className="h-5 w-5" />}
                  title={t("maintenance.map.empty.title")}
                  description={t("maintenance.map.empty.description")}
                  action={
                    <Button size="sm" onClick={() => setAddViewOpen(true)}>
                      <ImagePlus className="h-3.5 w-3.5" />
                      {t("maintenance.map.view.add")}
                    </Button>
                  }
                />
              </CardContent>
            </Card>
          )}

          {activeView && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
              <div className="space-y-4">
                <Card>
                  <CardHeader className="flex-wrap gap-2">
                    <CardTitle>{activeView.label}</CardTitle>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        variant={addMode ? "default" : "outline"}
                        onClick={() => {
                          setAddMode((prev) => !prev);
                          closeForm();
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        {addMode ? t("maintenance.map.view.addModeOn") : t("maintenance.map.view.addModeOff")}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setReplaceViewOpen(true)}>
                        <ImagePlus className="h-3.5 w-3.5" />
                        {t("maintenance.map.view.replace")}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          if (!activeView) return;
                          deleteView.mutate(activeView.id, {
                            onSuccess: () => {
                              toast.success(t("maintenance.map.view.deleted"));
                              closeForm();
                            },
                            onError: (error) => {
                              const message =
                                error instanceof ApiError && error.code === "VIEW_IN_USE"
                                  ? error.message
                                  : t("maintenance.map.view.deleteError");
                              toast.error(message);
                            },
                          });
                        }}
                        disabled={deleteView.isPending}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        {t("maintenance.map.view.delete")}
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {addMode && (
                      <p className="flex items-center gap-1.5 text-sm text-accent">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        {t("maintenance.map.view.addModeHint")}
                      </p>
                    )}
                    <ViewPhoto
                      view={activeView}
                      pins={pins}
                      onPick={addMode ? handlePick : undefined}
                      onPinClick={handlePinClick}
                      onPinMoveEnd={handlePinMoveEnd}
                    />
                  </CardContent>
                </Card>

                <Card className="lg:hidden">
                  <CardHeader>
                    <CardTitle>{t("maintenance.map.point.listTitle")}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 p-3">
                    <CheckpointsList
                      checkpoints={pins}
                      checkpointsData={visibleCheckpoints}
                      selectedId={selectedCheckpointId}
                      onSelect={handlePinClick}
                    />
                  </CardContent>
                </Card>
              </div>

              <div className="space-y-4">
                <Card className="hidden lg:block">
                  <CardHeader>
                    <CardTitle>{t("maintenance.map.point.listTitle")}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 p-3">
                    <CheckpointsList
                      checkpoints={pins}
                      checkpointsData={visibleCheckpoints}
                      selectedId={selectedCheckpointId}
                      onSelect={handlePinClick}
                    />
                  </CardContent>
                </Card>

                {(pendingPosition || selectedCheckpoint) && (
                  <CheckpointForm
                    checkpoint={selectedCheckpoint}
                    pendingPosition={pendingPosition ?? undefined}
                    isSaving={createCheckpoint.isPending || updateCheckpoint.isPending}
                    isArchiving={archiveCheckpoint.isPending}
                    onCancel={closeForm}
                    onSubmitCreate={(input) => {
                      if (!activeView) return;
                      createCheckpoint.mutate(
                        { viewId: activeView.id, input },
                        {
                          onSuccess: () => {
                            toast.success(t("maintenance.map.point.created"));
                            closeForm();
                            setAddMode(false);
                          },
                          onError: (error) =>
                            toast.error(t("maintenance.map.point.saveError"), {
                              description: error instanceof ApiError ? error.message : undefined,
                            }),
                        },
                      );
                    }}
                    onSubmitUpdate={(input) => {
                      if (!selectedCheckpoint) return;
                      updateCheckpoint.mutate(
                        { checkpointId: selectedCheckpoint.id, input },
                        {
                          onSuccess: () => {
                            toast.success(t("maintenance.map.point.saved"));
                            closeForm();
                          },
                          onError: (error) =>
                            toast.error(t("maintenance.map.point.saveError"), {
                              description: error instanceof ApiError ? error.message : undefined,
                            }),
                        },
                      );
                    }}
                    onArchive={
                      selectedCheckpoint
                        ? () =>
                            archiveCheckpoint.mutate(selectedCheckpoint.id, {
                              onSuccess: () => {
                                toast.success(t("maintenance.map.point.archived"));
                                closeForm();
                              },
                              onError: (error) =>
                                toast.error(t("maintenance.map.point.archiveError"), {
                                  description: error instanceof ApiError ? error.message : undefined,
                                }),
                            })
                        : undefined
                    }
                  />
                )}
              </div>
            </div>
          )}
        </>
      )}

      <ViewFormDialog
        open={addViewOpen}
        onOpenChange={setAddViewOpen}
        initialLabel=""
        requireImage
        isSaving={createView.isPending}
        onSubmit={({ label, image }) => {
          if (!equipmentId || !image) return;
          createView.mutate(
            { equipmentId, input: { label, image } },
            {
              onSuccess: (created) => {
                toast.success(t("maintenance.map.view.created"));
                setActiveViewId(created.id);
                setAddViewOpen(false);
              },
              onError: (error) =>
                toast.error(t("maintenance.map.view.createError"), {
                  description: error instanceof ApiError ? error.message : undefined,
                }),
            },
          );
        }}
      />

      <ViewFormDialog
        open={replaceViewOpen}
        onOpenChange={setReplaceViewOpen}
        initialLabel={activeView?.label ?? ""}
        requireImage={false}
        isSaving={updateView.isPending}
        onSubmit={({ label, image }) => {
          if (!activeView) return;
          updateView.mutate(
            { viewId: activeView.id, input: { label, image: image ?? undefined } },
            {
              onSuccess: () => {
                toast.success(t("maintenance.map.view.replaced"));
                setReplaceViewOpen(false);
              },
              onError: (error) =>
                toast.error(t("maintenance.map.view.replaceError"), {
                  description: error instanceof ApiError ? error.message : undefined,
                }),
            },
          );
        }}
      />
    </div>
  );
}

function CheckpointsList({
  checkpoints,
  checkpointsData,
  selectedId,
  onSelect,
}: {
  checkpoints: Pin[];
  checkpointsData: Checkpoint[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { t } = useI18n();
  const real = checkpoints.filter((p) => p.id !== "__pending__");
  if (real.length === 0) {
    return <p className="px-2 py-3 text-sm text-muted-foreground">{t("maintenance.map.point.listEmpty")}</p>;
  }
  return (
    <ul className="divide-y divide-border">
      {real.map((pin) => {
        const checkpoint = checkpointsData.find((c) => c.id === pin.id);
        if (!checkpoint) return null;
        return (
          <li key={pin.id}>
            <button
              type="button"
              onClick={() => onSelect(pin.id)}
              className={`flex min-h-11 w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted ${
                selectedId === pin.id ? "bg-muted" : ""
              }`}
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                {pin.n}
              </span>
              <span className="min-w-0 flex-1 truncate">{checkpoint.label}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
