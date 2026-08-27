import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Mail, Phone, Plus, UserRound } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { listOpportunities } from "../crm/opportunities/api";
import { listActivities } from "../crm/activities/api";
import { listOrders } from "../sales/api";
import { listInvoices } from "../finance/api";
import { createContact, listContacts, type Contact } from "./contactsApi";
import { getPartner } from "./api";

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
    <div className="grid gap-4 lg:grid-cols-3"><RecordList title="Opportunities" records={opportunities.map((item) => `${item.name} · ${item.stage} · $${item.amount}`)} /><RecordList title="Sales orders" records={orders.map((item) => `${item.id} · ${item.status} · $${item.total_amount}`)} /><RecordList title="Invoices" records={invoices.map((item) => `${item.id} · ${item.status} · ${item.amount} ${item.currency}`)} /></div>
  </div>;
}

function ContactRow({ contact }: { contact: Contact }) { return <div className="flex items-center gap-3 border-b pb-3 last:border-0"><UserRound className="h-8 w-8 rounded-full bg-muted p-1.5 text-muted-foreground" /><div className="min-w-0 text-sm"><p className="font-medium">{contact.first_name} {contact.last_name}{contact.is_primary && <span className="ml-2 text-xs text-primary">Primary</span>}</p><p className="text-muted-foreground">{contact.job_title || "Contact"}{contact.email ? ` · ${contact.email}` : ""}</p></div></div>; }
function RecordList({ title, records }: { title: string; records: string[] }) { return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">{records.length ? records.map((record) => <p key={record} className="border-b pb-2 last:border-0">{record}</p>) : <p className="text-muted-foreground">None yet.</p>}</CardContent></Card>; }
