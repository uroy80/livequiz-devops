// LiveQuiz – ONE-CLICK deployment pipeline
// Click "Build Now" (or git push) → GitHub code pulled → tests → Docker image → security scan
// → Terraform provisions AWS → image pushed to ECR → Ansible configures the server and deploys → smoke test.
pipeline {
  agent any
  options {
    timestamps()
    ansiColor('xterm')
    disableConcurrentBuilds()
    timeout(time: 45, unit: 'MINUTES')
  }
  environment {
    AWS_REGION        = 'ap-south-1'
    TF_IN_AUTOMATION  = '1'
    TF_STATE          = '/var/jenkins_home/state/livequiz.tfstate'
    LOCAL_IMAGE       = 'livequiz'
    ANSIBLE_FORCE_COLOR = '1'
  }
  stages {
    stage('1. Checkout from GitHub') {
      steps {
        script {
          env.GIT_SHORT = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
          env.APP_VERSION = readFile('VERSION').trim()
          env.TAG = "${env.APP_VERSION}-${env.BUILD_NUMBER}"
        }
        sh 'git log -1 --pretty="Commit %h by %an: %s"; git remote get-url origin'
      }
    }
    stage('2. Unit & Integration Tests') {
      steps {
        dir('app') {
          sh '''
            python3 -m venv .venv
            .venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
            .venv/bin/flake8 --max-line-length=160 --exclude=.venv,tests .
            .venv/bin/pytest -v --junitxml=test-results.xml tests
          '''
        }
      }
      post { always { junit 'app/test-results.xml' } }
    }
    stage('3. Build Docker Image') {
      steps {
        dir('app') {
          sh '''
            docker build -t "$LOCAL_IMAGE:$TAG" --build-arg APP_VERSION="$APP_VERSION" \
              --build-arg BUILD_NUMBER="$BUILD_NUMBER" --build-arg GIT_COMMIT="$GIT_COMMIT" .
            docker image ls "$LOCAL_IMAGE:$TAG"
          '''
        }
      }
    }
    stage('4. Security Scan') {
      steps {
        sh 'trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$LOCAL_IMAGE:$TAG"'
      }
    }
    stage('5. Terraform – Provision AWS') {
      steps {
        dir('infra/terraform') {
          sh '''
            aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output table
            mkdir -p "$(dirname "$TF_STATE")"
            MYIP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
            terraform init -input=false -backend-config="path=$TF_STATE"
            terraform fmt -check -recursive
            terraform validate
            terraform plan -input=false -var "admin_cidr=$MYIP/32" -out=tfplan
            terraform apply -input=false -auto-approve tfplan
            terraform output
          '''
        }
      }
    }
    stage('6. Push Image to Amazon ECR') {
      steps {
        dir('infra/terraform') {
          sh '''
            ECR=$(terraform output -raw ecr_repository_url)
            aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${ECR%%/*}"
            docker tag "$LOCAL_IMAGE:$TAG" "$ECR:$TAG"
            docker push -q "$ECR:$TAG"
            aws ecr describe-images --repository-name livequiz --image-ids imageTag="$TAG" \
              --query 'imageDetails[0].{tag:imageTags[0],pushed:imagePushedAt,sizeMB:imageSizeInBytes}' --output table
          '''
        }
      }
    }
    stage('7. Ansible – Configure & Deploy') {
      steps {
        sh '''
          cd infra/terraform
          umask 077
          terraform output -json | python3 -c '
import json,sys,os
o=json.load(sys.stdin)
json.dump({"image_tag":os.environ["TAG"],"build_number":os.environ["BUILD_NUMBER"],
           "db_password":o["db_password"]["value"],"admin_password":o["admin_password"]["value"],
           "secret_key":o["secret_key"]["value"]}, open("../ansible/.generated/vars.json","w"))'
          terraform output -raw admin_password > "$(dirname "$TF_STATE")/admin-password"
          cd ../ansible
          ansible-playbook site.yml -e @.generated/vars.json
        '''
      }
      post { always { sh 'rm -f infra/ansible/.generated/vars.json' } }
    }
    stage('8. Smoke Test (live on AWS)') {
      steps {
        dir('infra/terraform') {
          script {
            env.APP_URL = sh(script: 'terraform output -raw app_url', returnStdout: true).trim()
          }
          sh '''
            for i in $(seq 1 20); do curl -fsS "$APP_URL/healthz" | grep -q "\\"build\\":\\"$BUILD_NUMBER\\"" && break; sleep 3; done
            echo "Health:";        curl -fsS "$APP_URL/healthz"; echo
            echo "Stats API:";     curl -fsS "$APP_URL/api/stats"; echo
            echo "WebSocket handshake:"; curl -fsS "$APP_URL/socket.io/?EIO=4&transport=polling" | head -c 120; echo
            curl -fsS "$APP_URL/" | grep -q "Real-time quizzes"
            echo "SMOKE TEST PASSED"
          '''
        }
      }
    }
  }
  post {
    success {
      script { currentBuild.description = "LIVE: ${env.APP_URL} (v${env.TAG})" }
      echo """
      ==========================================================
        LiveQuiz is LIVE on AWS:  ${env.APP_URL}
        Players join at:          ${env.APP_URL}/play
        Version ${env.TAG} · commit ${env.GIT_SHORT}
      ==========================================================
      """
    }
    failure { echo 'Deployment failed – see the stage that turned red. Nothing is left half-switched: the previous containers keep running until Ansible replaces them.' }
  }
}
