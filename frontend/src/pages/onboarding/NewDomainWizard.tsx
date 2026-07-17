import { useNavigate } from 'react-router-dom'
import LivingAgentCanvas from '../../components/onboarding/LivingAgentCanvas'
import Stepper from '../../components/ui/Stepper'
import { GuideProvider, GuideRail } from '../../components/ui/FieldGuide'
import AccessStep from './steps/AccessStep'
import AgentStep from './steps/AgentStep'
import DomainStep from './steps/DomainStep'
import EntitiesStep from './steps/EntitiesStep'
import PublishStep from './steps/PublishStep'
import ToolsStep from './steps/ToolsStep'
import useNewDomainWizard, { WIZARD_STEPS } from './useNewDomainWizard'

export default function NewDomainWizard() {
  const navigate = useNavigate()
  const wizard = useNewDomainWizard()

  return (
    <GuideProvider>
      <div className="mx-auto max-w-6xl">
        <div className="mb-8 max-w-2xl">
          <span className="text-xs font-semibold tracking-wide text-brand-500 uppercase dark:text-brand-400">
            Onboarding
          </span>
          <h1 className="mt-1 bg-gradient-to-r from-brand-600 to-accent-500 bg-clip-text text-2xl font-bold tracking-tight text-transparent dark:from-brand-300 dark:to-accent-400">
            Onboard a new domain
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            Point Agent Forge at a database table and get a published text-to-SQL agent — the LLM writes every query
            itself at chat time, validated and row-level-scoped, so there's no SQL to author here at all.
          </p>
        </div>

        <Stepper steps={WIZARD_STEPS} currentIndex={wizard.step} className="mb-6 lg:hidden" />

        {/* On mobile the live canvas sits above the form (the 3-column grid
            below collapses to one column there); on lg+ it moves into the
            right-hand column alongside the guide rail instead. */}
        <div className="mb-6 lg:hidden">
          <LivingAgentCanvas
            domainName={wizard.domainName}
            domainDescription={wizard.domainDescription}
            policy={wizard.policy}
            entities={wizard.entities}
            tools={wizard.tools}
            agentName={wizard.agentName}
            agentDescription={wizard.agentDescription}
            agentInstruction={wizard.agentInstruction}
            smokeResult={wizard.smokeResult}
            publishedVersion={wizard.publishedVersion}
          />
        </div>

        <div className="grid gap-8 lg:grid-cols-[200px_minmax(0,1fr)_320px]">
          <div className="hidden lg:block">
            <div className="sticky top-4">
              <Stepper steps={WIZARD_STEPS} currentIndex={wizard.step} orientation="vertical" />
            </div>
          </div>

          <div>
            {wizard.step === 0 && (
              <DomainStep
                domainName={wizard.domainName}
                domainDescription={wizard.domainDescription}
                onDomainNameChange={wizard.setDomainName}
                onDomainDescriptionChange={wizard.setDomainDescription}
                onNext={wizard.next}
                canAdvance={wizard.validity.domain}
              />
            )}

            {wizard.step === 1 && (
              <AccessStep
                policy={wizard.policy}
                addingPolicy={wizard.addingPolicy}
                onPolicyCreated={wizard.setPolicy}
                onPolicyFormDone={wizard.finishPolicyStep}
                onChangePolicy={wizard.changePolicy}
                onSkip={wizard.skipPolicy}
              />
            )}

            {wizard.step === 2 && (
              <EntitiesStep
                entities={wizard.entities}
                addingEntity={wizard.addingEntity}
                onEntityCreated={wizard.addEntity}
                onEntityFormDone={wizard.finishEntityForm}
                onAddAnother={wizard.addAnotherEntity}
                onNext={wizard.next}
                canAdvance={wizard.validity.entities}
              />
            )}

            {wizard.step === 3 && (
              <ToolsStep
                entities={wizard.entities}
                tools={wizard.tools}
                isCreatingTools={wizard.isCreatingTools}
                onCreateAllTools={wizard.createAllTools}
                onNext={wizard.next}
                canAdvance={wizard.validity.tools}
              />
            )}

            {wizard.step === 4 && (
              <AgentStep
                domainName={wizard.domainName}
                domainDescription={wizard.domainDescription}
                tools={wizard.tools}
                agentName={wizard.agentName}
                agentDescription={wizard.agentDescription}
                agentInstruction={wizard.agentInstruction}
                onAgentNameChange={wizard.setAgentName}
                onAgentDescriptionChange={wizard.setAgentDescription}
                onAgentInstructionChange={wizard.setAgentInstruction}
                onUseSuggestedName={wizard.useSuggestedAgentName}
                onSubmit={wizard.createAgentAndAttachTools}
                isSubmitting={wizard.isCreatingAgent}
                canSubmit={wizard.validity.agent}
              />
            )}

            {wizard.step === 5 && (
              <PublishStep
                policy={wizard.policy}
                entities={wizard.entities}
                tools={wizard.tools}
                agentName={wizard.agentName}
                smokeResult={wizard.smokeResult}
                isRunningSmokeTest={wizard.isRunningSmokeTest}
                onRunSmokeTest={wizard.runSmokeTest}
                canPublish={wizard.validity.publish}
                isPublishing={wizard.isPublishing}
                publishError={wizard.publishError}
                publishedVersion={wizard.publishedVersion}
                onPublish={wizard.publish}
                onOpenPlayground={() => navigate(`/agents/${wizard.agent?.id}/playground`)}
                onOpenAgent={() => navigate(`/agents/${wizard.agent?.id}`)}
              />
            )}
          </div>

          <div className="hidden space-y-6 lg:block">
            <LivingAgentCanvas
              domainName={wizard.domainName}
              domainDescription={wizard.domainDescription}
              policy={wizard.policy}
              entities={wizard.entities}
              tools={wizard.tools}
              agentName={wizard.agentName}
              agentDescription={wizard.agentDescription}
              agentInstruction={wizard.agentInstruction}
              smokeResult={wizard.smokeResult}
              publishedVersion={wizard.publishedVersion}
            />
            <GuideRail />
          </div>
        </div>
      </div>
    </GuideProvider>
  )
}
