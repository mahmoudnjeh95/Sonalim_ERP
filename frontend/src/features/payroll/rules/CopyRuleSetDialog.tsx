import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { FormField } from "../../hr/FormField";
import { useCopyRuleSet, type RuleSetDocument, type RuleSetHeader } from "../api";
import { parseMonthInput } from "../format";

/** Copies a rule set (draft or confirmed) and every row of it into a new draft starting another month. */
export function CopyRuleSetDialog({
  open,
  onOpenChange,
  ruleSet,
  onCopied,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ruleSet: RuleSetHeader;
  onCopied?: (copy: RuleSetDocument) => void;
}) {
  const { t } = useI18n();
  const copy = useCopyRuleSet(ruleSet.id);
  const [name, setName] = useState(ruleSet.name);
  const [validFrom, setValidFrom] = useState("");

  useEffect(() => {
    if (open) {
      setName(ruleSet.name);
      setValidFrom("");
    }
  }, [open, ruleSet.id, ruleSet.name]);

  const submit = () =>
    copy
      .mutateAsync({ name: name.trim(), valid_from: parseMonthInput(validFrom) })
      .then((created) => {
        toast.success(t("payroll.rules.ruleSets.copied"));
        onCopied?.(created);
        onOpenChange(false);
      })
      .catch((error: Error) => toast.error(t("payroll.rules.actionFailed"), { description: error.message }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.rules.ruleSets.copy")}</DialogTitle>
          <DialogDescription>{t("payroll.rules.ruleSets.copyDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <FormField id="copy-rule-set-name" label={t("payroll.rules.ruleSets.name")}>
            <Input id="copy-rule-set-name" required value={name} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <FormField id="copy-rule-set-valid-from" label={t("payroll.rules.ruleSets.validFrom")}>
            <Input id="copy-rule-set-valid-from" type="month" required value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
          </FormField>
          <Button type="submit" className="w-full" disabled={copy.isPending}>
            {copy.isPending ? t("common.saving") : t("payroll.rules.ruleSets.copy")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
