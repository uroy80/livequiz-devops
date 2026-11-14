// Job DSL - both pipelines are created from code and read their Jenkinsfile from GitHub.
def repo = System.getenv('LQ_REPO_URL')

pipelineJob('LiveQuiz-Deploy') {
  description('ONE CLICK: pull code from GitHub → test → build image → scan → Terraform provisions AWS → push to ECR → Ansible deploys → smoke test. Also runs automatically on every git push.')
  logRotator { numToKeep(30) }
  properties { pipelineTriggers { triggers { pollSCM { scmpoll_spec('H/2 * * * *') } } } }
  definition {
    cpsScm {
      scm { git { remote { url(repo) }; branch('*/main') } }
      scriptPath('Jenkinsfile')
      lightweight(false)
    }
  }
}

pipelineJob('LiveQuiz-Destroy') {
  description('Removes everything Terraform created in AWS (EC2, VPC, ECR, IAM, alarms). Type "destroy" to confirm.')
  logRotator { numToKeep(10) }
  parameters { stringParam('CONFIRM', '', 'Type destroy to delete all AWS resources') }
  definition {
    cpsScm {
      scm { git { remote { url(repo) }; branch('*/main') } }
      scriptPath('Jenkinsfile.destroy')
      lightweight(false)
    }
  }
}
