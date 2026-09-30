import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Mail, Pencil, Phone, Plus, Tag as TagIcon, UserRound } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatXofWithCode } from "../../lib/currency";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { ActivityKindBadge } from "../../components/patterns/ActivityKindBadge";
import { AppLoader } from "../../components/patterns/AppLoader";
import { listOpportunities } from "../crm/opportunities/api";
import { listActivities } from "../crm/activities/api";
import { listOrders } from "../sales/api";
import { listInvoices } from "../finance/api";
import { createContact, listContacts, updateContact, type Contact } from "./contactsApi";
import { listProductTags, createProductTag, type ProductTag } from "../products/api";
import { getPartner, listTagsForPartner, setPartnerTags, updatePartnerTagLink, type PartnerTagLink } from "./api";

const EMPTY_CONTACT_FORM = { first_name: "", last_name: "", job_title: "", email: "", phone: "", is_primary: false };

export function PartnerDetailsPage() {
  const { partnerId } = useParams();
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [form, setForm] = useState(EMPTY_CONTACT_FORM);
  const queryKey = ["core", "partner", partnerId] as const;
  const { data: partner, isLoading } = useQuery({ queryKey, queryFn: () => getPartner(token, partnerId!) });
  const { data: contacts = [] } = useQuery({ queryKey: [...queryKey, "contacts"], queryFn: () => listContacts(token, partnerId!) });
  const { data: opportunities = [] } = useQuery({ queryKey: [...queryKey, "opportunities"], queryFn: () => listOpportunities(token, partnerId) });
  const { data: activities = [] } = useQuery({ queryKey: [...queryKey, "activities"], queryFn: () => listActivities(token).then((items) => items.filter((item) => item.subject_type === "partner" && item.subject_id === partnerId)) });
  const { data: orders = [] } = useQuery({ queryKey: [...queryKey, "orders"], queryFn: () => listOrders(token).then((items) => items.filter((item) => item.partner_id === partnerId)) });
  const { data: invoices = [] } = useQuery({ queryKey: [...queryKey, "invoices"], queryFn: () => listInvoices(token).then((items) => items.filter((item) => item.partner_id === partnerId)) });

  const contactMutation = useMutation({
    mutationFn: () => createContact(token, { partner_id: partnerId!, ...form }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [...queryKey, "contacts"] });
      setDialogOpen(false);
      setForm(EMPTY_CONTACT_FORM);
      toast.success(t("partners.details.contactAdded"));
    },
    onError: (error) => toast.error(t("partners.details.contactAddError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const updateContactMutation = useMutation({
    mutationFn: () => updateContact(token, editingContact!.id, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [...queryKey, "contacts"] });
      setDialogOpen(false);
      setEditingContact(null);
      setForm(EMPTY_CONTACT_FORM);
      toast.success(t("partners.details.contactUpdated"));
    },
    onError: (error) => toast.error(t("partners.details.contactUpdateError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  function openAddDialog() {
    setEditingContact(null);
    setForm(EMPTY_CONTACT_FORM);
    setDialogOpen(true);
  }

  function openEditDialog(contact: Contact) {
    setEditingContact(contact);
    setForm({
      first_name: contact.first_name,
      last_name: contact.last_name,
      job_title: contact.job_title ?? "",
      email: contact.email ?? "",
      phone: contact.phone ?? "",
      is_primary: contact.is_primary,
    });
    setDialogOpen(true);
  }

  if (isLoading || !partner) return <AppLoader label={t("partners.details.loading")} className="min-h-[220px]" />;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/crm/partners">
            <ArrowLeft className="h-4 w-4" />
            {t("partners.details.back")}
          </Link>
        </Button>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{partner.name}</h1>
          <p className="text-sm text-muted-foreground">
            {t("partners.details.subtitle")} · {t(`partners.kind.${partner.kind}` as Parameters<typeof t>[0])}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{t("partners.details.accountDetails")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {partner.industry && <p>{t("partners.details.industry")}: {partner.industry}</p>}
            {partner.email && (
              <p className="flex items-center gap-2">
                <Mail className="h-4 w-4" />
                {partner.email}
              </p>
            )}
            {partner.phone && (
              <p className="flex items-center gap-2">
                <Phone className="h-4 w-4" />
                {partner.phone}
              </p>
            )}
            <StatusBadge status={partner.status} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("partners.details.commercialSummary")}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-2 text-center text-sm">
            <div>
              <strong className="block text-xl">{opportunities.length}</strong>
              {t("partners.details.deals")}
            </div>
            <div>
              <strong className="block text-xl">{orders.length}</strong>
              {t("partners.details.orders")}
            </div>
            <div>
              <strong className="block text-xl">{invoices.length}</strong>
              {t("partners.details.invoices")}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("partners.details.openPipeline")}</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {formatXofWithCode(
              opportunities.filter((o) => !["won", "lost"].includes(o.stage)).reduce((sum, o) => sum + o.amount, 0),
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>{t("partners.details.contacts")}</CardTitle>
            <Dialog
              open={dialogOpen}
              onOpenChange={(open) => {
                setDialogOpen(open);
                if (!open) setEditingContact(null);
              }}
            >
              <DialogTrigger asChild>
                <Button size="sm" onClick={openAddDialog}>
                  <Plus className="h-4 w-4" />
                  {t("partners.details.addContact")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{editingContact ? t("partners.details.dialog.editTitle") : t("partners.details.dialog.addTitle")}</DialogTitle>
                  <DialogDescription>
                    {editingContact ? t("partners.details.dialog.editDescription") : t("partners.details.dialog.addDescription")}
                  </DialogDescription>
                </DialogHeader>
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (editingContact) updateContactMutation.mutate();
                    else contactMutation.mutate();
                  }}
                >
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label htmlFor="first-name">{t("partners.details.field.firstName")}</Label>
                      <Input id="first-name" required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
                    </div>
                    <div>
                      <Label htmlFor="last-name">{t("partners.details.field.lastName")}</Label>
                      <Input id="last-name" required value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
                    </div>
                  </div>
                  <Input
                    placeholder={t("partners.details.field.jobTitle")}
                    value={form.job_title}
                    onChange={(e) => setForm({ ...form, job_title: e.target.value })}
                  />
                  <Input
                    type="email"
                    placeholder={t("partners.details.field.email")}
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                  />
                  <Input
                    placeholder={t("partners.details.field.phone")}
                    value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
                    {t("partners.details.field.primaryContact")}
                  </label>
                  <Button type="submit" disabled={editingContact ? updateContactMutation.isPending : contactMutation.isPending}>
                    {editingContact
                      ? updateContactMutation.isPending
                        ? t("partners.details.saving")
                        : t("partners.details.updateContact")
                      : contactMutation.isPending
                        ? t("partners.details.saving")
                        : t("partners.details.saveContact")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          </CardHeader>
          <CardContent className="space-y-3">
            {contacts.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("partners.details.noContacts")}</p>
            ) : (
              contacts.map((contact) => <ContactRow key={contact.id} contact={contact} onEdit={() => openEditDialog(contact)} />)
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("partners.details.recentActivity")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {activities.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("partners.details.noActivities")}</p>
            ) : (
              activities.slice(0, 6).map((activity) => (
                <div key={activity.id} className="border-b pb-2 text-sm last:border-0">
                  <ActivityKindBadge kind={activity.kind} /> <span className="ml-2">{activity.note}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
      {(partner.kind === "supplier" || partner.kind === "both") && <PartnerTagsCard partnerId={partnerId!} />}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <RecordList
          title={t("partners.details.opportunities")}
          emptyLabel={t("partners.details.none")}
          records={opportunities.map((item) => `${item.name} · ${item.stage} · $${item.amount}`)}
        />
        <RecordList
          title={t("partners.details.salesOrders")}
          emptyLabel={t("partners.details.none")}
          records={orders.map((item) => `${item.id} · ${item.status} · $${item.total_amount}`)}
        />
        <RecordList
          title={t("partners.details.invoices")}
          emptyLabel={t("partners.details.none")}
          records={invoices.map((item) => `${item.id} · ${item.status} · ${item.amount} ${item.currency}`)}
        />
      </div>
    </div>
  );
}

function PartnerTagsCard({ partnerId }: { partnerId: string }) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const queryKey = ["core", "partners", partnerId, "tags"] as const;
  const { data: links = [] } = useQuery({ queryKey, queryFn: () => listTagsForPartner(token, partnerId) });
  const { data: allTags = [] } = useQuery({ queryKey: ["core", "product-tags"], queryFn: () => listProductTags(token) });
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);
  const [newTagName, setNewTagName] = useState("");

  useEffect(() => {
    setSelectedTagIds(links.map((link) => link.tag_id));
  }, [links]);

  const saveMutation = useMutation({
    mutationFn: () => setPartnerTags(token, partnerId, selectedTagIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      toast.success(t("partners.tags.saved"));
    },
    onError: (error) => toast.error(t("partners.tags.saveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const createTagMutation = useMutation({
    mutationFn: (name: string) => createProductTag(token, name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["core", "product-tags"] }),
  });

  const linkMutation = useMutation({
    mutationFn: ({ tagId, input }: { tagId: string; input: { is_preferred?: boolean; lead_time_days?: number; min_order_qty?: number } }) =>
      updatePartnerTagLink(token, partnerId, tagId, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    onError: (error) => toast.error(t("partners.tags.saveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const isDirty = selectedTagIds.length !== links.length || !links.every((link) => selectedTagIds.includes(link.tag_id));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <TagIcon className="h-4 w-4" />
          {t("partners.tags.title")}
        </CardTitle>
        <p className="text-sm text-muted-foreground">{t("partners.tags.description")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {allTags.map((tag: ProductTag) => {
            const selected = selectedTagIds.includes(tag.id);
            return (
              <button
                key={tag.id}
                type="button"
                onClick={() => setSelectedTagIds(selected ? selectedTagIds.filter((id) => id !== tag.id) : [...selectedTagIds, tag.id])}
              >
                <Badge variant={selected ? "primary" : "outline"}>{tag.name}</Badge>
              </button>
            );
          })}
        </div>
        <div className="flex gap-1.5">
          <Input value={newTagName} onChange={(e) => setNewTagName(e.target.value)} placeholder={t("products.field.newTag")} className="h-8 text-xs" />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              if (!newTagName.trim()) return;
              createTagMutation.mutate(newTagName.trim());
              setNewTagName("");
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
          <Button type="button" size="sm" onClick={() => saveMutation.mutate()} disabled={!isDirty || saveMutation.isPending}>
            {saveMutation.isPending ? t("partners.tags.saving") : t("partners.tags.save")}
          </Button>
        </div>
        {links.length > 0 && (
          <ul className="space-y-2">
            {links.map((link) => (
              <PartnerTagLinkRow key={link.tag_id} link={link} onUpdate={(input) => linkMutation.mutate({ tagId: link.tag_id, input })} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function PartnerTagLinkRow({
  link,
  onUpdate,
}: {
  link: PartnerTagLink;
  onUpdate: (input: { is_preferred?: boolean; lead_time_days?: number; min_order_qty?: number }) => void;
}) {
  const { t } = useI18n();
  const [leadTime, setLeadTime] = useState(link.lead_time_days?.toString() ?? "");
  const [minQty, setMinQty] = useState(link.min_order_qty?.toString() ?? "");

  useEffect(() => {
    setLeadTime(link.lead_time_days?.toString() ?? "");
    setMinQty(link.min_order_qty?.toString() ?? "");
  }, [link.lead_time_days, link.min_order_qty]);

  return (
    <li className="flex flex-wrap items-center gap-2 border-b border-border pb-2 text-sm last:border-0">
      <button type="button" onClick={() => onUpdate({ is_preferred: !link.is_preferred })}>
        <Badge variant={link.is_preferred ? "primary" : "outline"}>
          {link.tag_name}
          {link.is_preferred ? ` · ${t("partners.tags.preferred")}` : ""}
        </Badge>
      </button>
      <Input
        type="number"
        min={0}
        className="h-7 w-24 text-xs"
        placeholder={t("partners.tags.setLeadTime")}
        value={leadTime}
        onChange={(e) => setLeadTime(e.target.value)}
        onBlur={() => {
          const value = leadTime === "" ? undefined : Number(leadTime);
          if (value !== link.lead_time_days) onUpdate({ lead_time_days: value });
        }}
      />
      <span className="text-xs text-muted-foreground">{t("partners.tags.leadTimeDaysSuffix")}</span>
      <Input
        type="number"
        min={0}
        step="any"
        className="h-7 w-24 text-xs"
        placeholder={t("partners.tags.setMinOrderQty")}
        value={minQty}
        onChange={(e) => setMinQty(e.target.value)}
        onBlur={() => {
          const value = minQty === "" ? undefined : Number(minQty);
          if (value !== link.min_order_qty) onUpdate({ min_order_qty: value });
        }}
      />
      <span className="text-xs text-muted-foreground">{t("partners.tags.minOrderQtySuffix")}</span>
    </li>
  );
}

function ContactRow({ contact, onEdit }: { contact: Contact; onEdit: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 border-b pb-3 last:border-0">
      <UserRound className="h-8 w-8 rounded-full bg-muted p-1.5 text-muted-foreground" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">
          {contact.first_name} {contact.last_name}
          {contact.is_primary && <span className="ml-2 text-xs text-primary">{t("partners.details.primary")}</span>}
        </p>
        <p className="text-muted-foreground">
          {contact.job_title || t("partners.details.contactFallback")}
          {contact.email ? ` · ${contact.email}` : ""}
        </p>
      </div>
      <Button size="sm" variant="ghost" onClick={onEdit}>
        <Pencil className="h-3.5 w-3.5" />
        {t("partners.details.edit")}
      </Button>
    </div>
  );
}

function RecordList({ title, records, emptyLabel }: { title: string; records: string[]; emptyLabel: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {records.length ? (
          records.map((record) => (
            <p key={record} className="border-b pb-2 last:border-0">
              {record}
            </p>
          ))
        ) : (
          <p className="text-muted-foreground">{emptyLabel}</p>
        )}
      </CardContent>
    </Card>
  );
}
