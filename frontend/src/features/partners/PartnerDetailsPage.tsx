import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Mail, Phone, Plus, Tag as TagIcon, UserRound } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { listOpportunities } from "../crm/opportunities/api";
import { listActivities } from "../crm/activities/api";
import { listOrders } from "../sales/api";
import { listInvoices } from "../finance/api";
import { createContact, listContacts, type Contact } from "./contactsApi";
import { listProductTags, createProductTag, type ProductTag } from "../products/api";
import { getPartner, listTagsForPartner, setPartnerTags, updatePartnerTagLink, type PartnerTagLink } from "./api";

export function PartnerDetailsPage() {
  const { partnerId } = useParams();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ first_name: "", last_name: "", job_title: "", email: "", phone: "", is_primary: false });
  const queryKey = ["core", "partner", partnerId] as const;
  const { data: partner, isLoading } = useQuery({ queryKey, queryFn: () => getPartner(token, partnerId!) });
  const { data: contacts = [] } = useQuery({ queryKey: [...queryKey, "contacts"], queryFn: () => listContacts(token, partnerId!) });
  const { data: opportunities = [] } = useQuery({ queryKey: [...queryKey, "opportunities"], queryFn: () => listOpportunities(token, partnerId) });
  const { data: activities = [] } = useQuery({ queryKey: [...queryKey, "activities"], queryFn: () => listActivities(token).then((items) => items.filter((item) => item.subject_type === "partner" && item.subject_id === partnerId)) });
  const { data: orders = [] } = useQuery({ queryKey: [...queryKey, "orders"], queryFn: () => listOrders(token).then((items) => items.filter((item) => item.partner_id === partnerId)) });
  const { data: invoices = [] } = useQuery({ queryKey: [...queryKey, "invoices"], queryFn: () => listInvoices(token).then((items) => items.filter((item) => item.partner_id === partnerId)) });
  const contactMutation = useMutation({
    mutationFn: () => createContact(token, { partner_id: partnerId!, ...form }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: [...queryKey, "contacts"] }); setDialogOpen(false); setForm({ first_name: "", last_name: "", job_title: "", email: "", phone: "", is_primary: false }); toast.success("Contact added"); },
    onError: (error) => toast.error("Could not add contact", { description: error instanceof ApiError ? error.message : undefined }),
  });

  if (isLoading || !partner) return <p className="text-sm text-muted-foreground">Loading account...</p>;
  return <div className="space-y-6">
    <div className="flex items-start gap-3"><Button variant="ghost" size="sm" asChild><Link to="/crm/partners"><ArrowLeft className="h-4 w-4" />Accounts</Link></Button><div><h1 className="text-xl font-semibold tracking-tight">{partner.name}</h1><p className="text-sm text-muted-foreground">Third-party account  ·  {partner.kind}</p></div></div>
    <div className="grid gap-4 md:grid-cols-3"><Card><CardHeader><CardTitle>Account details</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">{partner.industry && <p>Industry: {partner.industry}</p>}{partner.email && <p className="flex items-center gap-2"><Mail className="h-4 w-4" />{partner.email}</p>}{partner.phone && <p className="flex items-center gap-2"><Phone className="h-4 w-4" />{partner.phone}</p>}<StatusBadge status={partner.status} /></CardContent></Card><Card><CardHeader><CardTitle>Commercial summary</CardTitle></CardHeader><CardContent className="grid grid-cols-3 gap-2 text-center text-sm"><div><strong className="block text-xl">{opportunities.length}</strong>Deals</div><div><strong className="block text-xl">{orders.length}</strong>Orders</div><div><strong className="block text-xl">{invoices.length}</strong>Invoices</div></CardContent></Card><Card><CardHeader><CardTitle>Open pipeline</CardTitle></CardHeader><CardContent className="text-2xl font-semibold">{new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(opportunities.filter((o) => !["won", "lost"].includes(o.stage)).reduce((sum, o) => sum + o.amount, 0))}</CardContent></Card></div>
    <div className="grid gap-4 lg:grid-cols-2"><Card><CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle>Contacts</CardTitle><Dialog open={dialogOpen} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button size="sm"><Plus className="h-4 w-4" />Add contact</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Add contact</DialogTitle><DialogDescription>Add a person connected to this account.</DialogDescription></DialogHeader><form className="space-y-3" onSubmit={(event) => { event.preventDefault(); contactMutation.mutate(); }}><div className="grid grid-cols-2 gap-3"><div><Label htmlFor="first-name">First name</Label><Input id="first-name" required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div><div><Label htmlFor="last-name">Last name</Label><Input id="last-name" required value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div></div><Input placeholder="Job title" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /><Input type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /><Input placeholder="Phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />Primary contact</label><Button type="submit" disabled={contactMutation.isPending}>Add contact</Button></form></DialogContent></Dialog></CardHeader><CardContent className="space-y-3">{contacts.length === 0 ? <p className="text-sm text-muted-foreground">No contacts yet.</p> : contacts.map((contact) => <ContactRow key={contact.id} contact={contact} />)}</CardContent></Card>
    <Card><CardHeader><CardTitle>Recent account activity</CardTitle></CardHeader><CardContent className="space-y-3">{activities.length === 0 ? <p className="text-sm text-muted-foreground">No activities logged.</p> : activities.slice(0, 6).map((activity) => <div key={activity.id} className="border-b pb-2 text-sm last:border-0"><StatusBadge status={activity.kind} /> <span className="ml-2">{activity.note}</span></div>)}</CardContent></Card></div>
    {(partner.kind === "supplier" || partner.kind === "both") && <PartnerTagsCard partnerId={partnerId!} />}
    <div className="grid gap-4 lg:grid-cols-3"><RecordList title="Opportunities" records={opportunities.map((item) => `${item.name} · ${item.stage} · $${item.amount}`)} /><RecordList title="Sales orders" records={orders.map((item) => `${item.id} · ${item.status} · $${item.total_amount}`)} /><RecordList title="Invoices" records={invoices.map((item) => `${item.id} · ${item.status} · ${item.amount} ${item.currency}`)} /></div>
  </div>;
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

function ContactRow({ contact }: { contact: Contact }) { return <div className="flex items-center gap-3 border-b pb-3 last:border-0"><UserRound className="h-8 w-8 rounded-full bg-muted p-1.5 text-muted-foreground" /><div className="min-w-0 text-sm"><p className="font-medium">{contact.first_name} {contact.last_name}{contact.is_primary && <span className="ml-2 text-xs text-primary">Primary</span>}</p><p className="text-muted-foreground">{contact.job_title || "Contact"}{contact.email ? ` · ${contact.email}` : ""}</p></div></div>; }
function RecordList({ title, records }: { title: string; records: string[] }) { return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">{records.length ? records.map((record) => <p key={record} className="border-b pb-2 last:border-0">{record}</p>) : <p className="text-muted-foreground">None yet.</p>}</CardContent></Card>; }
