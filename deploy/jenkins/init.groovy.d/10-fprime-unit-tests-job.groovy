// Creates (or updates) the pipeline job at startup. Idempotent; runs with controller privileges.
import hudson.model.ParametersDefinitionProperty
import hudson.model.StringParameterDefinition
import jenkins.model.Jenkins
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob

def name = 'fprime-unit-tests'
def script = new File('/usr/share/jenkins/ref/fprime-unit-tests.Jenkinsfile').text
def jenkins = Jenkins.get()
WorkflowJob job = jenkins.getItem(name) ?: jenkins.createProject(WorkflowJob, name)
job.setDescription('F´ unit tests for one branch. Triggered by the test-generation agent through the Jenkins MCP server.')
job.setDefinition(new CpsFlowDefinition(script, true))
job.removeProperty(ParametersDefinitionProperty)
job.addProperty(new ParametersDefinitionProperty([
    new StringParameterDefinition('BRANCH', 'HEAD', 'Branch, tag or commit of the F´ repository'),
    new StringParameterDefinition('MODULES', 'Svc/ComStub', 'Space-separated F´ components'),
]))
job.save()
println "[oge] pipeline job '${name}' ready"
