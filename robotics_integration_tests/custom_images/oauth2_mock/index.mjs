// Local OpenID Connect issuer for the robotics integration tests.
//
// Replaces Azure Entra ID so the suite needs no app registrations, no tenant and
// no client secrets. Services (ISAR, Flotilla, SARA) point their OIDC discovery at
// this container; the pytest process mints its own tokens against the same issuer.
//
// Design notes:
//
//   * `issuer.url` is the *in-network* alias, so the `iss` claim, the discovery
//     document and the JWKS URI all agree regardless of who is asking. The pytest
//     process talks to the published host port but receives tokens whose `iss` is
//     the in-network name -- which is exactly what the services validate against.
//
//   * The built-in discovery document is used as-is. The upstream CoreDM reference
//     replaces it in order to advertise a `localhost` authorization_endpoint for a
//     browser; this suite is entirely machine-to-machine (client credentials), so
//     that complication is not needed here.
//
//   * `idp` and `acct` are deliberately never emitted. `fastapi-azure-auth`'s
//     `is_guest()` treats `acct === 1`, or an `idp` that differs from `iss`, as a
//     guest user and rejects the token with 403 before signature validation.
//
//   * The signing key is built by hand rather than via `issuer.keys.generate()`,
//     purely so it can carry `use: "sig"`. `fastapi-azure-auth` filters the JWKS
//     with `if key.get('use') == 'sig'` and silently loads *zero* keys otherwise,
//     failing with "Unable to verify token, no signing keys found". `generate()`
//     accepts only `kid` and `crv`, so it cannot produce that field.

import { generateKeyPairSync } from 'node:crypto'

import { OAuth2Server, Events } from 'oauth2-mock-server'

const PORT = Number(process.env.PORT ?? 8080)
const ISSUER_URL = process.env.ISSUER_URL ?? `http://oauth-mock:${PORT}`

// Fake tenant id. Only needs to be stable and non-empty; nothing validates it
// against Entra, but Flotilla and SARA read `tid` off the principal.
const TENANT_ID = process.env.TENANT_ID ?? 'integration-test-tenant'

// Roles stamped on every token unless a caller asks for something narrower via
// POST /issue-token. Union of what the three services require:
//   Role.Admin                          flotilla super-admin (AccessRoleService.cs:38)
//   Role.User.{HUA,KAA,NLS}             per-installation roles seeded by the tests
//   Mission.Control                     ISAR's REQUIRED_ROLE
const DEFAULT_ROLES = [
    'Role.Admin',
    'Role.User.HUA',
    'Role.User.KAA',
    'Role.User.NLS',
    'Mission.Control',
]

/**
 * Turn a requested scope or resource into an `aud` claim.
 *
 * Callers ask for things like `isar-test/.default`, `api://isar-test/.default`
 * or `api://isar-test/user_impersonation`. All of those must land on `isar-test`,
 * because that is what the service compares its configured client id against.
 */
function audienceFromScope(scope) {
    if (!scope) return undefined
    // Client credentials may request several space-separated scopes; they all
    // belong to one resource, so the first is representative.
    const first = String(scope).trim().split(/\s+/)[0]
    if (!first) return undefined
    const withoutPrefix = first.replace(/^api:\/\//, '')
    // Strip the trailing permission segment (`/.default`, `/user_impersonation`).
    const slash = withoutPrefix.lastIndexOf('/')
    return slash === -1 ? withoutPrefix : withoutPrefix.slice(0, slash)
}

const KEY_ID = 'integration-test-key'

const server = new OAuth2Server()

const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
await server.issuer.keys.add({
    ...privateKey.export({ format: 'jwk' }),
    kid: KEY_ID,
    alg: 'RS256',
    use: 'sig',
})
server.issuer.url = ISSUER_URL

// Lets POST /issue-token hand a specific role set to the token signer without
// threading state through the library's request pipeline.
const requestedRoles = new Map()

server.service.on(Events.BeforeTokenSigning, (token, req) => {
    const body = req.body ?? {}
    const audience = audienceFromScope(body.scope ?? body.resource)

    token.payload.iss = ISSUER_URL
    if (audience) token.payload.aud = audience

    // `ver` is required by fastapi-azure-auth's Claims model as a
    // Literal['1.0', '2.0']; without it the token validates but User construction
    // raises a pydantic ValidationError surfaced as a generic 401.
    token.payload.ver = '2.0'
    token.payload.tid = TENANT_ID
    token.payload.sub = String(body.client_id ?? 'integration-tests')
    token.payload.oid = String(body.client_id ?? 'integration-tests')
    token.payload.appid = String(body.client_id ?? 'integration-tests')
    token.payload.name = 'Integration Tests'
    token.payload.preferred_username = 'integration-tests@example.com'

    const override = body.roles_token ? requestedRoles.get(body.roles_token) : undefined
    if (body.roles_token) requestedRoles.delete(body.roles_token)
    token.payload.roles = override ?? DEFAULT_ROLES

    // `iss`, `iat`, `exp` and `nbf` are set by the library. fastapi-azure-auth
    // requires all four (plus `aud` and `sub`) and rejects the token with
    // MissingRequiredClaimError otherwise, so fail loudly here rather than
    // producing tokens that 401 deep inside a service.
    for (const claim of ['iss', 'iat', 'exp', 'nbf', 'sub', 'aud', 'ver']) {
        if (token.payload[claim] === undefined) {
            throw new Error(`Refusing to sign token: required claim '${claim}' is missing`)
        }
    }

    // Guard against reintroducing the guest-user claims. See the header comment.
    delete token.payload.idp
    delete token.payload.acct
})

/**
 * Mint a token with an explicit audience and role set.
 *
 * Used by negative tests: a wrong audience must produce 401, and a missing role
 * must produce 403. Body: { "audience": "flotilla-test", "roles": ["Role.Admin"] }
 */
server.service.addRoute('POST', '/issue-token', async (req, res) => {
    const body = req.body ?? {}
    const audience = body.audience
    const roles = body.roles ?? DEFAULT_ROLES

    if (!audience) {
        res.writeHead(400, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'invalid_request', error_description: 'audience is required' }))
        return
    }

    const token = await server.issuer.buildToken({
        kid: KEY_ID,
        scopesOrTransform: (header, payload) => {
            payload.iss = ISSUER_URL
            payload.aud = audience
            payload.ver = '2.0'
            payload.tid = TENANT_ID
            payload.sub = 'integration-tests'
            payload.oid = 'integration-tests'
            payload.appid = 'integration-tests'
            payload.name = 'Integration Tests'
            payload.preferred_username = 'integration-tests@example.com'
            payload.roles = roles
            delete payload.idp
            delete payload.acct
        },
    })

    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ access_token: token, token_type: 'Bearer', expires_in: 3600 }))
})

await server.start(PORT, '0.0.0.0')
console.log(`oauth2 mock issuer listening on 0.0.0.0:${PORT}, issuer=${ISSUER_URL}`)
