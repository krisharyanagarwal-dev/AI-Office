const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const HIVE = '/Users/aryanagarwal/openalice-fleet/hive';
const AGENTS_DIR = path.join(HIVE, 'agents');

const registry = JSON.parse(fs.readFileSync(path.join(HIVE, 'registry.json'), 'utf8'));
const agents = registry.agents;

const template = fs.readFileSync('/Users/aryanagarwal/openalice-fleet/hive/agents/canonical_agent_template.js', 'utf8');

const specialistDirs = [];
for (let i = 1; i <= 28; i++) {
  specialistDirs.push('specialist-' + String(i).padStart(2, '0'));
}

const agentDirs = [
  'god', 'office-manager', 'mainbot',
  'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
  'worker-angela', 'worker-dwight', 'worker-jim', 'worker-kevin', 'worker-oscar', 'worker-pam', 'worker-toby',
  'pm-research', 'pm-data', 'pm-signal', 'pm-risk', 'pm-attribution', 'pm-audit', 'pm-validation', 'pm-ops',
].concat(specialistDirs);

console.log('Deploying canonical template to all agents...');

for (const agentDir of agentDirs) {
  const filepath = path.join(AGENTS_DIR, agentDir, 'bin', 'agent_manager.js');
  
  let agentInfo = agents[agentDir];
  if (!agentInfo) {
    for (const [aid, info] of Object.entries(agents)) {
      if (aid.toLowerCase() === agentDir.toLowerCase()) {
        agentInfo = info;
        break;
      }
    }
  }
  
  if (!agentInfo && agentDir.startsWith('f') && agentDir[1] && agentDir[1].match(/\d/)) {
    const aid = 'F' + agentDir.substring(1);
    if (agents[aid]) agentInfo = agents[aid];
  }
  
  if (!agentInfo) {
    agentInfo = { id: agentDir, name: agentDir, role: 'agent', floor: 'unknown' };
  }
  
  let content = template
    .replace(/%AGENT_ID%/g, agentInfo.id)
    .replace(/%AGENT_NAME%/g, agentInfo.name)
    .replace(/%AGENT_ROLE%/g, agentInfo.role)
    .replace(/%AGENT_FLOOR%/g, agentInfo.floor || 'unknown');
  
  const binDir = path.dirname(filepath);
  if (!fs.existsSync(binDir)) fs.mkdirSync(binDir, { recursive: true });
  fs.writeFileSync(filepath, content);
  
  console.log(`Deployed: ${agentDir} (id=${agentInfo.id}, name=${agentInfo.name}, role=${agentInfo.role})`);
}

console.log('\nVerifying syntax for all agents...');
let allPass = true;
for (const agentDir of agentDirs) {
  const filepath = path.join(AGENTS_DIR, agentDir, 'bin', 'agent_manager.js');
  const result = spawnSync('node', ['-c', filepath], { encoding: 'utf8' });
  if (result.status !== 0) {
    console.error(`FAIL: ${agentDir}`);
    console.error(result.stderr.toString());
    allPass = false;
  } else {
    console.log(`OK: ${agentDir}`);
  }
}

if (allPass) {
  console.log('\n✅ All agents pass syntax check!');
} else {
  console.error('\n❌ Some agents failed syntax check');
  process.exit(1);
}
