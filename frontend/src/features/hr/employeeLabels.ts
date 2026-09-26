import type { BadgeProps } from "../../components/ui/badge";
import type { TranslationKey } from "../../lib/i18n";
import type {
  ContractStatus,
  ContractType,
  DependantKind,
  DocumentKind,
  DocumentState,
  EmployeeStatus,
  EndReason,
  Gender,
  MaritalStatus,
  MobileOperator,
  PayFrequency,
  PaymentMethodKind,
} from "./api";

type Variant = NonNullable<BadgeProps["variant"]>;

export const EMPLOYEE_STATUS_LABEL: Record<EmployeeStatus, TranslationKey> = {
  active: "hr.employeeStatus.active",
  on_leave: "hr.employeeStatus.on_leave",
  inactive: "hr.employeeStatus.inactive",
  terminated: "hr.employeeStatus.terminated",
};
export const EMPLOYEE_STATUS_VARIANT: Record<EmployeeStatus, Variant> = {
  active: "success",
  on_leave: "warning",
  inactive: "default",
  terminated: "destructive",
};
export const GENDER_LABEL: Record<Gender, TranslationKey> = { male: "hr.gender.male", female: "hr.gender.female" };
export const MARITAL_LABEL: Record<MaritalStatus, TranslationKey> = {
  single: "hr.marital.single",
  married: "hr.marital.married",
  divorced: "hr.marital.divorced",
  widowed: "hr.marital.widowed",
};
export const END_REASON_LABEL: Record<EndReason, TranslationKey> = {
  term_reached: "hr.endReason.term_reached",
  resignation: "hr.endReason.resignation",
  dismissal: "hr.endReason.dismissal",
  trial_termination: "hr.endReason.trial_termination",
  mutual_agreement: "hr.endReason.mutual_agreement",
  retirement: "hr.endReason.retirement",
  death: "hr.endReason.death",
  amended: "hr.endReason.amended",
  other: "hr.endReason.other",
};
export const CONTRACT_TYPE_LABEL: Record<ContractType, TranslationKey> = {
  cdi: "hr.contractType.cdi",
  cdd: "hr.contractType.cdd",
  apprentice: "hr.contractType.apprentice",
  daily: "hr.contractType.daily",
  intern: "hr.contractType.intern",
};
export const CONTRACT_STATUS_LABEL: Record<ContractStatus, TranslationKey> = {
  draft: "hr.contractStatus.draft",
  active: "hr.contractStatus.active",
  expired: "hr.contractStatus.expired",
  terminated: "hr.contractStatus.terminated",
};
export const CONTRACT_STATUS_VARIANT: Record<ContractStatus, Variant> = {
  draft: "default",
  active: "success",
  expired: "outline",
  terminated: "destructive",
};
export const PAY_FREQUENCY_LABEL: Record<PayFrequency, TranslationKey> = { monthly: "hr.payFrequency.monthly", daily: "hr.payFrequency.daily" };
export const PAYMENT_METHOD_LABEL: Record<PaymentMethodKind, TranslationKey> = {
  bank: "hr.paymentMethod.bank",
  mobile_money: "hr.paymentMethod.mobile_money",
  cash: "hr.paymentMethod.cash",
};
export const OPERATOR_LABEL: Record<MobileOperator, TranslationKey> = { orange_money: "hr.operator.orange_money", moov_money: "hr.operator.moov_money" };
export const DEPENDANT_KIND_LABEL: Record<DependantKind, TranslationKey> = { spouse: "hr.dependantKind.spouse", child: "hr.dependantKind.child" };
export const DOCUMENT_KIND_LABEL: Record<DocumentKind, TranslationKey> = {
  id_card: "hr.documentKind.id_card",
  passport: "hr.documentKind.passport",
  work_permit: "hr.documentKind.work_permit",
  medical_certificate: "hr.documentKind.medical_certificate",
  driving_licence: "hr.documentKind.driving_licence",
  diploma: "hr.documentKind.diploma",
  criminal_record: "hr.documentKind.criminal_record",
  signed_contract: "hr.documentKind.signed_contract",
  other: "hr.documentKind.other",
};
export const DOCUMENT_STATE_LABEL: Record<DocumentState, TranslationKey> = {
  expired: "hr.documentState.expired",
  expiring: "hr.documentState.expiring",
  valid: "hr.documentState.valid",
};
export const DOCUMENT_STATE_VARIANT: Record<DocumentState, Variant> = { expired: "destructive", expiring: "warning", valid: "success" };
