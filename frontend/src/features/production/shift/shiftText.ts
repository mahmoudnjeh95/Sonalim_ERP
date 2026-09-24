import { useCallback } from "react";
import { useI18n } from "../../../lib/i18n";

/**
 * The shift screen's words, kept beside the screen instead of in the app-wide
 * dictionary: the columns of nine paper tables alone are a hundred labels, and they
 * change with the fiches, not with the rest of the app.
 */
export interface Label {
  en: string;
  fr: string;
}

export const L = (en: string, fr: string): Label => ({ en, fr });

/** Resolve a label in the language the user picked. */
export function useLabel() {
  const { language } = useI18n();
  return useCallback((label: Label) => label[language], [language]);
}

export const T = {
  title: L("Shift report", "Fiche de shift"),
  subtitle: L(
    "One report per line and shift. Fill each section as the paper fiche, then hand it in.",
    "Un rapport par ligne et par shift. Remplissez chaque section comme la fiche papier, puis validez-la.",
  ),
  date: L("Date", "Date"),
  line: L("Line", "Ligne"),
  shift: L("Shift", "Shift"),
  team: L("Team", "Équipe"),
  conducteur: L("Line operator", "Conducteur ligne"),
  agentFabrication: L("Fabrication agent", "Agent de fabrication"),
  machiniste: L("Machine operator", "Machiniste"),
  aideMachiniste: L("Machine assistant", "Aide machiniste"),
  openShift: L("Open this shift", "Ouvrir ce shift"),
  openHint: L(
    "No report exists for this line, date and shift yet.",
    "Aucun rapport n'existe encore pour cette ligne, cette date et ce shift.",
  ),
  noLines: L("No production line is set up yet.", "Aucune ligne de production n'est configurée."),
  noAccess: L(
    "You do not have access to shift reports. Ask an administrator for the shift report permission.",
    "Vous n'avez pas accès aux rapports de shift. Demandez la permission à un administrateur.",
  ),
  loading: L("Loading the shift…", "Chargement du shift…"),
  today: L("Today", "Aujourd'hui"),
  yesterday: L("Yesterday", "Hier"),
  currentShift: L("Current shift", "Poste actuel"),
  prevDay: L("Previous day", "Jour précédent"),
  nextDay: L("Next day", "Jour suivant"),
  refresh: L("Refresh shift", "Actualiser le rapport"),
  lastUpdated: L("Updated at", "Mis à jour à"),
  kiosk: L("Fullscreen mode", "Mode plein écran"),
  exitKiosk: L("Exit fullscreen", "Quitter le plein écran"),
  printSheet: L("Print shift sheet", "Imprimer la feuille de poste"),
  kpiSemolina: L("Semoule poured", "Semoule versée"),
  kpiFinished: L("Finished output", "Produit fini"),
  kpiYield: L("Shift yield", "Rendement poste"),
  kpiStops: L("Total downtime", "Temps d'arrêt"),
  kpiWaste: L("Waste", "Déchets"),

  progress: L("Sections handed in", "Sections rendues"),
  resizeColumn: L("Drag to resize the column", "Glisser pour redimensionner la colonne"),
  resetColumns: L("Reset column widths", "Rétablir les largeurs des colonnes"),
  history: L("History", "Historique"),
  historyTitle: L("Revision history", "Historique des révisions"),
  noHistory: L("Nothing has been handed in on this section yet.", "Rien n'a encore été rendu sur cette section."),
  latest: L("Latest", "Dernière"),
  legacySnapshot: L(
    "This revision comes from the old Daily / Conditionnement report and is kept as it was filed.",
    "Cette révision provient de l'ancien rapport Journalier / Conditionnement et est conservée telle que déposée.",
  ),
  allIn: L("Every section is in. The shift is with the validator.", "Toutes les sections sont rendues. Le shift est chez le validateur."),
  toGo: L("to go", "à rendre"),
  validated: L("Validated", "Validé"),
  validatedHint: L("This shift is validated and can no longer be edited.", "Ce shift est validé et ne peut plus être modifié."),
  returnedHint: L("A validator sent sections back. Fix them and hand them in again.", "Un validateur a renvoyé des sections. Corrigez-les et rendez-les à nouveau."),

  status: {
    empty: L("Not started", "Pas commencé"),
    draft: L("Draft", "Brouillon"),
    submitted: L("Handed in", "Rendu"),
    nothing_to_report: L("Nothing to report", "Rien à signaler"),
    returned: L("Sent back", "Renvoyé"),
  },
  shiftStatus: {
    open: L("In progress", "En cours"),
    submitted: L("With the validator", "Chez le validateur"),
    validated: L("Validated", "Validé"),
    returned: L("Sent back", "Renvoyé"),
  },

  saveDraft: L("Save draft", "Enregistrer le brouillon"),
  submit: L("Hand in", "Rendre"),
  saveChanges: L("Save changes", "Enregistrer les modifications"),
  nothing: L("Nothing to report", "Rien à signaler"),
  addRow: L("Add a row", "Ajouter une ligne"),
  removeRow: L("Remove this row", "Supprimer cette ligne"),
  emptyRows: L("No rows yet.", "Aucune ligne pour l'instant."),
  expand: L("Semoule lines", "Lignes de semoule"),
  addSemolina: L("Add a semoule line", "Ajouter une ligne de semoule"),
  choose: L("Choose…", "Choisir…"),
  unsaved: L("Unsaved changes", "Modifications non enregistrées"),
  revised: L("Revised after hand-in", "Modifié après remise"),
  revision: L("Revision", "Révision"),
  sentBackBy: L("Sent back", "Renvoyé"),

  saved: L("Saved", "Enregistré"),
  handedIn: L("Handed in", "Rendu"),
  markedEmpty: L("Marked as nothing to report", "Marqué comme rien à signaler"),
  opened: L("Shift opened", "Shift ouvert"),
  headerSaved: L("Names saved", "Noms enregistrés"),
  failed: L("That did not work", "Cela n'a pas fonctionné"),
  fixFirst: L("Save or fix the highlighted values first.", "Enregistrez ou corrigez d'abord les valeurs signalées."),
  // The validator's side
  awaitingTitle: L("Shift reports to validate", "Rapports de shift à valider"),
  awaitingHint: L(
    "Every section of these shifts has been handed in. Approve the whole shift, or send back the sections that need fixing.",
    "Toutes les sections de ces shifts ont été rendues. Approuvez le shift entier, ou renvoyez les sections à corriger.",
  ),
  noneAwaiting: L("No shift is waiting for validation.", "Aucun shift n'attend de validation."),
  review: L("Review", "Examiner"),
  reviewTitle: L("Review the shift", "Examiner le shift"),
  approve: L("Approve shift", "Approuver le shift"),
  approving: L("Approving…", "Approbation…"),
  sendBack: L("Send back", "Renvoyer"),
  sendBackSections: L("Send back the ticked sections", "Renvoyer les sections cochées"),
  tickToSendBack: L("Tick to send back", "Cocher pour renvoyer"),
  sendBackReason: L("Why are they sent back?", "Pourquoi les renvoyer ?"),
  sendBackReasonHint: L("The team sees this on each returned section.", "L'équipe le voit sur chaque section renvoyée."),
  editSection: L("Edit this section", "Modifier cette section"),
  cancelCorrection: L("Cancel correction", "Annuler la correction"),
  editSectionReason: L("Why are you correcting this?", "Pourquoi corrigez-vous ceci ?"),
  saveCorrection: L("Save correction", "Enregistrer la correction"),
  savingCorrection: L("Saving…", "Enregistrement…"),
  correctionSaved: L("Correction saved", "Correction enregistrée"),
  editedByValidator: L("Edited by validator", "Modifié par le validateur"),
  unlock: L("Unlock", "Déverrouiller"),
  relock: L("Cancel unlock", "Annuler le déverrouillage"),
  unlockReason: L("Why are you correcting this? (optional)", "Pourquoi corrigez-vous ceci ? (facultatif)"),
  saveUnlockedEdit: L("Save correction", "Enregistrer la correction"),
  unlockedEditSaved: L("Correction saved", "Correction enregistrée"),
  editedAfterValidation: L("Edited after validation", "Modifié après validation"),
  shortfallTitle: L("Stock is short for this shift", "Le stock est insuffisant pour ce shift"),
  shortfallHint: L(
    "The shift uses more than the stock holds. Explain why, then approve again.",
    "Le shift consomme plus que le stock. Expliquez pourquoi, puis approuvez à nouveau.",
  ),
  approved: L("Shift approved", "Shift approuvé"),
  bulkApprove: L("Bulk approve all complete", "Approuver en masse tous les complets"),
  bulkApproving: L("Approving…", "Approbation…"),
  bulkApproved: (count: number) => L(`${count} shift(s) approved`, `${count} shift(s) approuvé(s)`),
  sentBack: L("Sections sent back", "Sections renvoyées"),
  changedSince: L(
    "A section changed while you were reviewing. The shift has been reloaded; review it again.",
    "Une section a changé pendant l'examen. Le shift a été rechargé ; examinez-le à nouveau.",
  ),
  revisedNote: L("Edited after hand-in", "Modifié après remise"),
  nothingSection: L("Nothing to report on this section.", "Rien à signaler sur cette section."),
  confirmNothing: L(
    "This removes the rows in this section. Continue?",
    "Cela supprime les lignes de cette section. Continuer ?",
  ),
} as const;
