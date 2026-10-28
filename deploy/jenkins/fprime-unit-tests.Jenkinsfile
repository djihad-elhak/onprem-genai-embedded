// F´ unit tests for one branch of the F´ repository mounted at /repos/fprime (read-only).
// Triggered by the test-generation agent through the Jenkins MCP server (tool triggerBuild).
// Result: FAILURE when a component does not build, UNSTABLE when a unit test fails (JUnit report).
pipeline {
    agent any
    options {
        timeout(time: 90, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '50'))
        disableConcurrentBuilds()
    }
    parameters {
        string(name: 'BRANCH', defaultValue: 'HEAD', description: 'Branch, tag or commit of the F´ repository')
        string(name: 'MODULES', defaultValue: 'Svc/ComStub', description: 'Space-separated F´ components')
    }
    environment {
        FPRIME_REPO = '/repos/fprime'
    }
    stages {
        stage('Checkout') {
            steps {
                sh '''
                    set -eu
                    rm -rf fprime reports && mkdir reports
                    git -c protocol.file.allow=always clone --quiet --no-checkout "$FPRIME_REPO" fprime
                    cd fprime
                    git checkout --quiet "origin/$BRANCH" 2>/dev/null || git checkout --quiet "$BRANCH"
                    # googletest comes from the mounted checkout: no network access needed
                    git config submodule.googletest.url "$FPRIME_REPO/googletest"
                    git -c protocol.file.allow=always submodule update --init --quiet
                    git log -1 --format='Testing %h (%an): %s'
                '''
            }
        }
        stage('Unit-test build cache') {
            steps {
                sh '''
                    cd fprime
                    fprime-util generate --ut > ../reports/generate.log 2>&1 || { tail -n 60 ../reports/generate.log; exit 1; }
                '''
            }
        }
        stage('Unit tests') {
            steps {
                sh '''
                    set -u
                    status=0
                    for m in $MODULES; do
                        echo "=== $m"
                        target=$(echo "$m" | tr / _)
                        if ! (cd "fprime/$m" && fprime-util build --ut -j"$(nproc)"); then
                            echo "build failed: $m"; status=1; continue
                        fi
                        exe=$(ls fprime/build-fprime-automatic-native-ut/bin/*/"${target}_ut_exe")
                        (cd "fprime/$m" && "$WORKSPACE/$exe" --gtest_output="xml:$WORKSPACE/reports/${target}.xml") || true
                        if [ ! -s "reports/${target}.xml" ]; then
                            echo "no test report for $m (crash?)"; status=1
                        fi
                    done
                    exit $status
                '''
            }
        }
    }
    post {
        always {
            junit testResults: 'reports/*.xml', allowEmptyResults: true
        }
    }
}
