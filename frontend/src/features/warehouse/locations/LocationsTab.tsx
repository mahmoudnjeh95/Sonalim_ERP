import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { FolderPlus, MapPin, Move as MoveIcon, Pencil, Plus } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { Popover, PopoverTrigger, PopoverContent } from "../../../components/ui/popover";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../../components/patterns/EmptyState";
import SiteIcon from "../../../assets/icons/warehouse/site.svg?react";
import ZoneIcon from "../../../assets/icons/warehouse/zone.svg?react";
import AisleIcon from "../../../assets/icons/warehouse/aisle.svg?react";
import RackIcon from "../../../assets/icons/warehouse/drying-rack.svg?react";
import BinIcon from "../../../assets/icons/warehouse/box.svg?react";
import { updateLocation, type Location, type LocationType } from "../api";
import { getLocationTree, listSites, locationTreeQueryKey, reparentLocation, SITES_QUERY_KEY, type Site } from "./api";
import { SiteDialog } from "./SiteDialog";
import { LocationDialog } from "./LocationDialog";

const TYPE_ICON: Record<LocationType, typeof SiteIcon> = { zone: ZoneIcon, aisle: AisleIcon, rack: RackIcon, bin: BinIcon };

function LocationTypeIcon({ type, className }: { type: LocationType; className?: string }) {
  const Icon = TYPE_ICON[type];
  return <Icon className={className ?? "h-4 w-4 text-muted-foreground"} />;
}

const editLocationSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
});
type EditLocationForm = z.infer<typeof editLocationSchema>;

function EditLocationDialog({
  open,
  onOpenChange,
  location,
  siteId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  location: Location | null;
  siteId: string;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const form = useForm<EditLocationForm>({ resolver: zodResolver(editLocationSchema), defaultValues: { code: "", name: "" } });

  useEffect(() => {
    if (open && location) form.reset({ code: location.code, name: location.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, location]);

  const mutation = useMutation({
    mutationFn: (input: EditLocationForm) => updateLocation(token, location!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: locationTreeQueryKey(siteId) });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("warehouse.locations.dialog.edit.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.locations.dialog.edit.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => mutation.mutate(input))}>
          <div className="space-y-1.5">
            <Label htmlFor="loc-edit-code">{t("warehouse.locations.field.code")}</Label>
            <Input id="loc-edit-code" {...form.register("code")} />
            {form.formState.errors.code && <p className="text-sm text-destructive">{form.formState.errors.code.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-edit-name">{t("warehouse.locations.field.name")}</Label>
            <Input id="loc-edit-name" {...form.register("name")} />
            {form.formState.errors.name && <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>}
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.locations.dialog.error")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {t("warehouse.sites.dialog.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MovePopover({ location, candidates, siteId }: { location: Location; candidates: Location[]; siteId: string }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");

  const mutation = useMutation({
    mutationFn: () => reparentLocation(token, location.id, target || null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: locationTreeQueryKey(siteId) });
      setOpen(false);
    },
  });

  const options = candidates.filter((candidate) => candidate.id !== location.id);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setTarget(location.parent_location_id ?? "");
      }}
    >
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" title={t("warehouse.locations.action.move")}>
          <MoveIcon className="h-3.5 w-3.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent>
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase text-muted-foreground">{t("warehouse.locations.action.move")}</p>
          <Select value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="">{t("warehouse.locations.field.parent.none")}</option>
            {options.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name} ({candidate.code})
              </option>
            ))}
          </Select>
          {mutation.isError && (
            <p className="text-xs text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.locations.dialog.error")}
            </p>
          )}
          <Button size="sm" className="w-full" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {t("warehouse.locations.action.move")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function RowActions({
  location,
  locations,
  siteId,
  canManage,
  canAdmin,
  onAddChild,
  onEdit,
}: {
  location: Location;
  locations: Location[];
  siteId: string;
  canManage: boolean;
  canAdmin: boolean;
  onAddChild: (parentId: string) => void;
  onEdit: (location: Location) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-1">
      {canManage && (
        <Button variant="ghost" size="sm" onClick={() => onAddChild(location.id)} title={t("warehouse.locations.action.addChild")}>
          <FolderPlus className="h-3.5 w-3.5" />
        </Button>
      )}
      {canAdmin && <MovePopover location={location} candidates={locations} siteId={siteId} />}
      {canAdmin && (
        <Button variant="ghost" size="sm" onClick={() => onEdit(location)} title={t("warehouse.locations.action.edit")}>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

const LOCATION_TYPE_FILTERS = ["all", "zone", "aisle", "rack", "bin"] as const;
type LocationTypeFilter = (typeof LOCATION_TYPE_FILTERS)[number];
const NO_SITE_QUERY_KEY = ["warehouse", "locations", "tree", "none"] as const;

export function LocationsTab() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;

  const { data: sites = [] } = useQuery({ queryKey: SITES_QUERY_KEY, queryFn: () => listSites(token) });
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(null);
  useEffect(() => {
    if (!selectedSiteId && sites.length > 0) setSelectedSiteId(sites[0].id);
  }, [sites, selectedSiteId]);

  const { data: locations = [] } = useQuery({
    queryKey: selectedSiteId ? locationTreeQueryKey(selectedSiteId) : NO_SITE_QUERY_KEY,
    queryFn: () => getLocationTree(token, selectedSiteId!),
    enabled: selectedSiteId !== null,
  });

  const [typeFilter, setTypeFilter] = useState<LocationTypeFilter>("all");
  const [siteDialogOpen, setSiteDialogOpen] = useState(false);
  const [editingSite, setEditingSite] = useState<Site | null>(null);
  const [locationDialogOpen, setLocationDialogOpen] = useState(false);
  const [newLocationParentId, setNewLocationParentId] = useState<string | null>(null);
  const [editingLocation, setEditingLocation] = useState<Location | null>(null);

  const canManageSites = hasPermission("warehouse.manage_sites");
  const canAdminSites = hasPermission("warehouse.admin_sites");
  const canManageLocations = hasPermission("warehouse.manage_stock");
  const canAdminLocations = hasPermission("warehouse.admin_locations");

  const depthById = useMemo(() => {
    const map = new Map<string, number>();
    for (const loc of locations) {
      const parentDepth = loc.parent_location_id ? (map.get(loc.parent_location_id) ?? 0) : -1;
      map.set(loc.id, parentDepth + 1);
    }
    return map;
  }, [locations]);

  const nameById = useMemo(() => new Map(locations.map((loc) => [loc.id, loc.name])), [locations]);

  const columnFilters = useColumnFilters<Location>([
    { key: "name", kind: "text", getValue: (row) => row.name },
    { key: "code", kind: "text", getValue: (row) => row.code },
  ]);

  const columns: ColumnDef<Location>[] = [
    {
      key: "name",
      header: t("warehouse.locations.column.name"),
      defaultWidth: 260,
      cell: (row) => (
        <div className="flex items-center gap-1.5" style={{ paddingLeft: (depthById.get(row.id) ?? 0) * 16 }}>
          <LocationTypeIcon type={row.location_type} />
          <span className="truncate">{row.name}</span>
        </div>
      ),
      filterCell: {
        type: "text",
        placeholder: t("warehouse.locations.column.name"),
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
      },
    },
    {
      key: "code",
      header: t("warehouse.locations.column.code"),
      cell: (row) => <span className="font-mono text-xs">{row.code}</span>,
      filterCell: {
        type: "text",
        placeholder: t("warehouse.locations.column.code"),
        value: columnFilters.text.code ?? "",
        onChange: (v) => columnFilters.setTextValue("code", v),
      },
    },
    {
      key: "type",
      header: t("warehouse.locations.column.type"),
      cell: (row) => <Badge variant="outline">{t(`warehouse.locations.type.${row.location_type}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "parent",
      header: t("warehouse.locations.column.parent"),
      cell: (row) => (
        <span className="text-muted-foreground">{row.parent_location_id ? (nameById.get(row.parent_location_id) ?? "—") : "—"}</span>
      ),
      filterCell: { type: "blank" },
    },
    {
      key: "blocked",
      header: t("warehouse.locations.column.blocked"),
      cell: (row) =>
        row.is_blocked ? <Badge variant="destructive">{t("warehouse.locations.blocked")}</Badge> : <span className="text-muted-foreground">—</span>,
      filterCell: { type: "blank" },
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) => (
        <RowActions
          location={row}
          locations={locations}
          siteId={selectedSiteId ?? ""}
          canManage={canManageLocations}
          canAdmin={canAdminLocations}
          onAddChild={(parentId) => {
            setNewLocationParentId(parentId);
            setLocationDialogOpen(true);
          }}
          onEdit={(loc) => setEditingLocation(loc)}
        />
      ),
      filterCell: { type: "blank" },
    },
  ];

  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.locations",
    columns,
  );

  const filteredByType = typeFilter === "all" ? locations : locations.filter((loc) => loc.location_type === typeFilter);
  const rows = columnFilters.apply(filteredByType);

  if (sites.length === 0) {
    return (
      <EmptyState
        icon={<SiteIcon className="h-5 w-5" />}
        title={t("warehouse.sites.empty.title")}
        description={t("warehouse.sites.empty.description")}
        action={
          canManageSites ? (
            <Button
              size="sm"
              onClick={() => {
                setEditingSite(null);
                setSiteDialogOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              {t("warehouse.sites.newSite")}
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={selectedSiteId ?? ""} onChange={(event) => setSelectedSiteId(event.target.value)} className="w-56">
          {sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.name} ({site.code})
              {!site.is_active ? ` — ${t("warehouse.sites.inactive")}` : ""}
            </option>
          ))}
        </Select>
        {canAdminSites && selectedSiteId && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setEditingSite(sites.find((s) => s.id === selectedSiteId) ?? null);
              setSiteDialogOpen(true);
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
            {t("warehouse.sites.editSite")}
          </Button>
        )}
        {canManageSites && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditingSite(null);
              setSiteDialogOpen(true);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("warehouse.sites.newSite")}
          </Button>
        )}
        <div className="flex-1" />
        {canManageLocations && selectedSiteId && (
          <Button
            size="sm"
            onClick={() => {
              setNewLocationParentId(null);
              setLocationDialogOpen(true);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("warehouse.locations.newLocation")}
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <FilterTabs
          value={typeFilter}
          onChange={setTypeFilter}
          options={LOCATION_TYPE_FILTERS.map((type) => ({
            value: type,
            label: type === "all" ? t("common.all") : t(`warehouse.locations.type.${type}`),
          }))}
        />
        {columnFilters.isActive && (
          <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </div>

      {rows.length === 0 ? (
        <EmptyState icon={<MapPin className="h-5 w-5" />} title={t("warehouse.locations.empty.title")} description={t("warehouse.locations.empty.description")} />
      ) : (
        <Table colWidths={colWidths}>
          <TableHeader>
            <TableRow>
              {visibleColumns.map((column) => (
                <ResizableTableHead key={column.key} width={getWidth(column.key)} onResize={(width) => setWidth(column.key, width)}>
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <SiteDialog open={siteDialogOpen} onOpenChange={setSiteDialogOpen} site={editingSite} />
      {selectedSiteId && (
        <LocationDialog
          open={locationDialogOpen}
          onOpenChange={setLocationDialogOpen}
          siteId={selectedSiteId}
          locations={locations}
          defaultParentId={newLocationParentId}
        />
      )}
      {selectedSiteId && (
        <EditLocationDialog
          open={editingLocation !== null}
          onOpenChange={(open) => {
            if (!open) setEditingLocation(null);
          }}
          location={editingLocation}
          siteId={selectedSiteId}
        />
      )}
    </div>
  );
}
