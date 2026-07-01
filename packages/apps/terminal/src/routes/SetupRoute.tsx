/**
 * SetupRoute — multi-step first-time setup wizard orchestrator.
 * Modes: Quick (2 steps), Guided (7 steps), Advanced (9 steps).
 * Saves to connectionStore + settingsStore, then navigates based on persona.
 *
 * Step components live in ./setup/
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { motionConfig } from "@/lib/motion";
import PublicRouteShell from "@/components/layout/PublicRouteShell";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import { ModeSelection } from "./setup/ModeSelection";
import type { SetupMode } from "./setup/ModeSelection";
import { StepIndicator } from "./setup/StepIndicator";
import { ConnectionStep } from "./setup/ConnectionStep";
import type { ConnectionFormValues } from "./setup/ConnectionStep";
import { PersonaPicker, ExperiencePicker, InterestPicker, NameInput } from "./setup/PersonaStep";
import type { Persona, ExperienceLevel } from "./setup/PersonaStep";
import { TradingStep } from "./setup/TradingStep";
import type { TradingDefaultsFormValues } from "./setup/TradingStep";
import { RiskStep } from "./setup/RiskStep";
import type { RiskFormValues } from "./setup/RiskStep";
import { LlmStep } from "./setup/LlmStep";
import { LayoutPreview, DoneScreen } from "./setup/ReviewStep";
import { persistSetupChoices } from "./setup/applySetupChoices";

// ---------------------------------------------------------------------------
// Wizard state
// ---------------------------------------------------------------------------

interface WizardState {
  persona: Persona | null;
  experience: ExperienceLevel | null;
  connection: ConnectionFormValues | null;
  tradingDefaults: TradingDefaultsFormValues | null;
  riskLimits: RiskFormValues | null;
  name: string;
  interests: string[];
}

const INITIAL_WIZARD: WizardState = {
  persona: null,
  experience: null,
  connection: null,
  tradingDefaults: null,
  riskLimits: null,
  name: "Trader",
  interests: [],
};

// ---------------------------------------------------------------------------
// Step labels per mode
// ---------------------------------------------------------------------------

const QUICK_STEPS    = ["Connection", "Persona"];
const GUIDED_STEPS   = ["Persona", "Connection", "Experience", "Interests", "Trading Defaults", "Preview", "Done"];
const ADVANCED_STEPS = [
  "Persona", "Connection", "Experience", "Interests",
  "Trading Defaults", "Risk Limits", "AI Config", "Preview", "Done",
];

function stepsForMode(mode: SetupMode): string[] {
  if (mode === "quick") return QUICK_STEPS;
  if (mode === "guided") return GUIDED_STEPS;
  return ADVANCED_STEPS;
}

// ---------------------------------------------------------------------------
// Main SetupRoute
// ---------------------------------------------------------------------------

export default function SetupRoute() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<SetupMode | null>(null);
  const [step, setStep] = useState(0);
  const [wizard, setWizard] = useState<WizardState>(INITIAL_WIZARD);

  function applyAndNavigate(w: WizardState) {
    const persona = w.persona ?? "trader";
    const destination = persistSetupChoices({
      persona,
      experience: w.experience,
      connection: w.connection,
      tradingDefaults: w.tradingDefaults,
      riskLimits: w.riskLimits,
      name: w.name,
      interests: w.interests,
    });

    navigate(destination);
  }

  function toggleInterest(id: string) {
    setWizard((w) => ({
      ...w,
      interests: w.interests.includes(id)
        ? w.interests.filter((i) => i !== id)
        : [...w.interests, id],
    }));
  }

  function next() { setStep((s) => s + 1); }
  function back() {
    if (step === 0) setMode(null);
    else setStep((s) => s - 1);
  }

  // ---------- Mode selection ----------
  if (!mode) {
    return (
      <ModeSelection
        onSelect={(m) => { setMode(m); setStep(0); }}
      />
    );
  }

  // ---------- Wizard shell ----------
  const steps = stepsForMode(mode);
  const totalSteps = steps.length;
  const stepLabel = steps[step] ?? "";

  // Shared steps used by both Guided and Advanced (same step indices 0–4)
  function renderSharedStep(): React.ReactNode | null {
    if (step === 0) {
      return (
        <div className="space-y-5">
          <NameInput value={wizard.name} onChange={(name) => setWizard((w) => ({ ...w, name }))} />
          <PersonaPicker selected={wizard.persona} onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))} />
          <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground" disabled={!wizard.persona} onClick={next}>
            Continue <ArrowRight className="size-4 ml-2" />
          </Button>
        </div>
      );
    }
    if (step === 1) {
      return (
        <ConnectionStep
          defaultValues={wizard.connection ?? undefined}
          onComplete={(vals) => { setWizard((w) => ({ ...w, connection: vals })); next(); }}
        />
      );
    }
    if (step === 2) {
      return (
        <div className="space-y-5">
          <ExperiencePicker selected={wizard.experience} onSelect={(e) => setWizard((w) => ({ ...w, experience: e }))} />
          <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground" disabled={!wizard.experience} onClick={next}>
            Continue <ArrowRight className="size-4 ml-2" />
          </Button>
        </div>
      );
    }
    if (step === 3) {
      return (
        <div className="space-y-5">
          <p className="text-sm text-text-secondary">Select one or more areas you are interested in.</p>
          <InterestPicker selected={wizard.interests} onToggle={toggleInterest} />
          <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground" disabled={wizard.interests.length === 0} onClick={next}>
            Continue <ArrowRight className="size-4 ml-2" />
          </Button>
        </div>
      );
    }
    if (step === 4) {
      return (
        <TradingStep
          defaultValues={wizard.tradingDefaults ?? undefined}
          onComplete={(vals) => { setWizard((w) => ({ ...w, tradingDefaults: vals })); next(); }}
        />
      );
    }
    return null;
  }

  function renderPreviewStep(): React.ReactNode {
    return (
      <div className="space-y-5">
        <LayoutPreview experience={wizard.experience ?? "intermediate"} interests={wizard.interests} />
        <p className="text-text-muted text-xs">You can change your layout anytime from the workspace menu.</p>
        <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground" onClick={next}>
          Continue <ArrowRight className="size-4 ml-2" />
        </Button>
      </div>
    );
  }

  function renderStep() {
    // QUICK: 0=Connection, 1=Persona
    if (mode === "quick") {
      if (step === 0) {
        return (
          <ConnectionStep
            defaultValues={wizard.connection ?? undefined}
            onComplete={(vals) => { setWizard((w) => ({ ...w, connection: vals })); next(); }}
          />
        );
      }
      if (step === 1) {
        return (
          <div className="space-y-5">
            <NameInput value={wizard.name} onChange={(name) => setWizard((w) => ({ ...w, name }))} />
            <PersonaPicker selected={wizard.persona} onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))} />
            <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground" disabled={!wizard.persona} onClick={() => applyAndNavigate(wizard)}>
              Launch FlintTrade <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
    }

    // GUIDED: 0=Persona, 1=Connection, 2=Experience, 3=Interests, 4=TradingDefaults, 5=Preview, 6=Done
    if (mode === "guided") {
      if (step <= 4) return renderSharedStep();
      if (step === 5) return renderPreviewStep();
      if (step === 6) return <DoneScreen persona={wizard.persona ?? "trader"} name={wizard.name} onGo={() => applyAndNavigate(wizard)} />;
    }

    // ADVANCED: 0=Persona, 1=Connection, 2=Experience, 3=Interests, 4=TradingDefaults,
    //           5=RiskLimits, 6=LLM, 7=Preview, 8=Done
    if (mode === "advanced") {
      if (step <= 4) return renderSharedStep();
      if (step === 5) {
        return (
          <RiskStep
            defaultValues={wizard.riskLimits ?? undefined}
            onComplete={(vals) => { setWizard((w) => ({ ...w, riskLimits: vals })); next(); }}
          />
        );
      }
      if (step === 6) return <LlmStep onComplete={next} />;
      if (step === 7) return renderPreviewStep();
      if (step === 8) return <DoneScreen persona={wizard.persona ?? "trader"} name={wizard.name} onGo={() => applyAndNavigate(wizard)} />;
    }

    return null;
  }

  const isDoneStep =
    (mode === "guided" && step === 6) || (mode === "advanced" && step === 8);

  const reduced = motionConfig.prefersReducedMotion();

  const stepVariants = {
    initial: { opacity: 0, x: reduced ? 0 : 20 },
    animate: {
      opacity: 1,
      x: 0,
      transition: { duration: motionConfig.duration.slow, ease: motionConfig.ease.enter },
    },
    exit: {
      opacity: 0,
      x: reduced ? 0 : -20,
      transition: { duration: motionConfig.duration.fast, ease: motionConfig.ease.exit },
    },
  };

  return (
      <PublicRouteShell mainLabel="Setup wizard" maxWidth="sm" contentClassName="py-6 sm:py-8">
        <div className="w-full space-y-6">
          {/* Header */}
          <div className="text-center space-y-1">
              <p className="text-accent/80 text-xxs uppercase tracking-[0.32em]">FlintTrade Setup</p>
              <AnimatePresence mode="wait">
                <motion.h2
                  key={`label-${step}`}
                  initial={{ opacity: 0, y: reduced ? 0 : -4 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: motionConfig.duration.normal, ease: motionConfig.ease.enter } }}
                  exit={{ opacity: 0, y: reduced ? 0 : 4, transition: { duration: motionConfig.duration.fast, ease: motionConfig.ease.exit } }}
                  className="font-heading text-2xl font-bold text-text-primary"
                >
                  {stepLabel}
                </motion.h2>
              </AnimatePresence>
          </div>

          {/* Progress dots */}
          <StepIndicator total={totalSteps} current={step} onStepClick={(i) => setStep(i)} />

          {/* Card with slide transitions */}
          <Card className="overflow-hidden rounded-xl border-border-default/70 bg-surface-card/70 shadow-2xl shadow-black/20 backdrop-blur-xl">
            <CardContent className="pt-6 pb-6 px-6">
              <AnimatePresence mode="wait">
                <motion.div
                  key={step}
                  variants={stepVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  {renderStep()}
                </motion.div>
              </AnimatePresence>
            </CardContent>
          </Card>

          {/* Navigation */}
          {!isDoneStep && (
            <div className="flex justify-between items-center">
              <Button
                variant="ghost"
                size="sm"
                onClick={back}
                className="text-sm text-text-muted hover:text-text-primary"
              >
                <ArrowLeft className="size-3.5 mr-1.5" />
                {step === 0 ? "Change mode" : "Back"}
              </Button>
              <span className="font-mono text-xs text-text-muted">
                {step + 1} / {totalSteps}
              </span>
            </div>
          )}
        </div>
      </PublicRouteShell>
  );
}
