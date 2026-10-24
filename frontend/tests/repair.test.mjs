import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'

async function loadProfile(jobs, cached) {
  const storage = new Map(cached ? [['resumeId', '1'], ['resumeProfile:1', JSON.stringify(cached)]] : [])
  const context = vm.createContext({ localStorage: { getItem: (key) => storage.get(key) ?? null } })
  const module = new vm.SourceTextModule(fs.readFileSync(new URL('../src/services/userService.js', import.meta.url), 'utf8'), { context })
  await module.link(async (name) => {
    const exports = name.includes('jobService') ? { getRecommendedJobs: async () => jobs }
      : name.includes('authSession') ? { getAccessToken: () => null, setAccessToken: () => {} }
        : { apiRequest: () => { throw new Error('Unexpected API request') } }
    return new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
    }, { context })
  })
  await module.evaluate()
  return module.namespace.getUserProfile({ name: 'Real Candidate' })
}

test('missing resume never supplies mock personal values', async () => {
  const profile = await loadProfile([], null)
  assert.equal(profile.skills.length, 0)
  assert.equal(profile.suggestions.length, 0)
  assert.equal(profile.statistics.profileMatch, null)
  assert.equal(profile.statistics.missingSkills, null)
  assert.equal(profile.education.cgpa, undefined)
  assert.equal(profile.analysisAvailable, false)
})

test('skill summaries use returned jobs and deduplicate', async () => {
  const job = { matchedSkills: ['Python'], missingSkills: ['SQL'], requiredSkills: ['Python', 'SQL'] }
  const profile = await loadProfile([job, job], { skills: ['Python'], education: 'BTech\nExample College\n2020-2024' })
  assert.equal(profile.matchedSkills.join(','), 'Python')
  assert.equal(profile.missingSkills.join(','), 'SQL')
  assert.equal(profile.statistics.missingSkills, 1)
  assert.equal(profile.analysisAvailable, true)
  assert.equal(profile.education.cgpa, undefined)
})

test('unsupported experience and employment filters are absent', () => {
  const source = fs.readFileSync(new URL('../src/pages/RecommendedJobs.jsx', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /job\.experience|job\.employmentType|filter-experience|filter-type/)
  assert.match(source, /job\.workMode/)
  assert.match(source, /job\.location/)
})
