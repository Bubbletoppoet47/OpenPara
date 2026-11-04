/* cfea.c - native kernels for the tetrahedral FEA of OpenPara's Mesh FEA add-on.
   Plain C (no Python headers), loaded with ctypes.  GPL-3.0 like the rest of OpenPara.
   Build:  gcc -O3 -fopenmp -shared -fPIC cfea.c -o cfea.so -lm        (see build.py)            */
#include <math.h>
#include <stdint.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#define MAXN 10
static const int EDGE[6][2] = {{0,1},{1,2},{2,0},{0,3},{1,3},{2,3}};   /* VTK order of mid-edge nodes, as tet.py EDGES */

int cfea_version(void) { return 3; }

int cfea_threads(void) {
#ifdef _OPENMP
    return omp_get_max_threads();
#else
    return 1;
#endif
}

void cfea_set_threads(int n) {
#ifdef _OPENMP
    if (n > 0) omp_set_num_threads(n);
#else
    (void)n;
#endif
}

/* shape function derivatives wrt the 4 volume coordinates at L: dN[node][4] */
static void dnd(int order, const double *L, double dN[MAXN][4]) {
    int i, k;
    if (order == 1) {
        for (i = 0; i < 4; i++) for (k = 0; k < 4; k++) dN[i][k] = (i == k);
        return;
    }
    for (i = 0; i < MAXN; i++) for (k = 0; k < 4; k++) dN[i][k] = 0.0;
    for (i = 0; i < 4; i++) dN[i][i] = 4 * L[i] - 1;
    for (k = 0; k < 6; k++) {
        int a = EDGE[k][0], b = EDGE[k][1];
        dN[4 + k][a] = 4 * L[b];
        dN[4 + k][b] = 4 * L[a];
    }
}

/* gradients of the volume coordinates (4x3) and volume of one element; returns 0 for a degenerate element */
static int grad_L(const double *x, double gL[4][3], double *vol) {
    double a[3] = {x[3]-x[0], x[4]-x[1], x[5]-x[2]};
    double b[3] = {x[6]-x[0], x[7]-x[1], x[8]-x[2]};
    double c[3] = {x[9]-x[0], x[10]-x[1], x[11]-x[2]};
    /* J has columns a, b, c;  rows of inv(J) are the gradients of L1, L2, L3 */
    double inv[3][3];
    {
        double M[3][3] = {{a[0], b[0], c[0]}, {a[1], b[1], c[1]}, {a[2], b[2], c[2]}};
        double d = M[0][0]*(M[1][1]*M[2][2]-M[1][2]*M[2][1]) - M[0][1]*(M[1][0]*M[2][2]-M[1][2]*M[2][0]) + M[0][2]*(M[1][0]*M[2][1]-M[1][1]*M[2][0]);
        double r;
        if (d == 0.0 || d != d) return 0;
        r = 1.0 / d;
        inv[0][0] = (M[1][1]*M[2][2]-M[1][2]*M[2][1]) * r;  inv[0][1] = (M[0][2]*M[2][1]-M[0][1]*M[2][2]) * r;  inv[0][2] = (M[0][1]*M[1][2]-M[0][2]*M[1][1]) * r;
        inv[1][0] = (M[1][2]*M[2][0]-M[1][0]*M[2][2]) * r;  inv[1][1] = (M[0][0]*M[2][2]-M[0][2]*M[2][0]) * r;  inv[1][2] = (M[0][2]*M[1][0]-M[0][0]*M[1][2]) * r;
        inv[2][0] = (M[1][0]*M[2][1]-M[1][1]*M[2][0]) * r;  inv[2][1] = (M[0][1]*M[2][0]-M[0][0]*M[2][1]) * r;  inv[2][2] = (M[0][0]*M[1][1]-M[0][1]*M[1][0]) * r;
        *vol = fabs(d) / 6.0;
    }
    int k;
    for (k = 0; k < 3; k++) { gL[1][k] = inv[0][k]; gL[2][k] = inv[1][k]; gL[3][k] = inv[2][k]; }
    for (k = 0; k < 3; k++) gL[0][k] = -(gL[1][k] + gL[2][k] + gL[3][k]);
    return 1;
}

/* element stiffness (3n x 3n, row major) from the 4 corner coordinates; D = 6x6 material matrix */
static int element_ke(int order, const double *x, const double *D, double *Ke, double *vol_out) {
    static const double pt4[4][4] = {{0.5854101966249685, 0.1381966011250105, 0.1381966011250105, 0.1381966011250105},
                                     {0.1381966011250105, 0.5854101966249685, 0.1381966011250105, 0.1381966011250105},
                                     {0.1381966011250105, 0.1381966011250105, 0.5854101966249685, 0.1381966011250105},
                                     {0.1381966011250105, 0.1381966011250105, 0.1381966011250105, 0.5854101966249685}};
    static const double pt1[1][4] = {{0.25, 0.25, 0.25, 0.25}};
    double gL[4][3], vol;
    int n = order == 2 ? 10 : 4, ng = order == 2 ? 4 : 1, g, i, j, k, r, c;
    int nd = 3 * n;
    double wt = (order == 2 ? 0.25 : 1.0);
    if (!grad_L(x, gL, &vol)) return 0;
    *vol_out = vol;
    for (i = 0; i < nd * nd; i++) Ke[i] = 0.0;
    for (g = 0; g < ng; g++) {
        double dN[MAXN][4], gr[MAXN][3], B[6][3 * MAXN], DB[6][3 * MAXN];
        dnd(order, order == 2 ? pt4[g] : pt1[0], dN);
        for (i = 0; i < n; i++) for (k = 0; k < 3; k++)
            gr[i][k] = dN[i][0]*gL[0][k] + dN[i][1]*gL[1][k] + dN[i][2]*gL[2][k] + dN[i][3]*gL[3][k];
        for (r = 0; r < 6; r++) for (c = 0; c < nd; c++) B[r][c] = 0.0;
        for (i = 0; i < n; i++) {                       /* strain order xx yy zz xy yz xz (engineering shear) */
            B[0][3*i]   = gr[i][0];
            B[1][3*i+1] = gr[i][1];
            B[2][3*i+2] = gr[i][2];
            B[3][3*i]   = gr[i][1];  B[3][3*i+1] = gr[i][0];
            B[4][3*i+1] = gr[i][2];  B[4][3*i+2] = gr[i][1];
            B[5][3*i]   = gr[i][2];  B[5][3*i+2] = gr[i][0];
        }
        for (r = 0; r < 6; r++) for (c = 0; c < nd; c++) {
            double s = 0.0;
            for (k = 0; k < 6; k++) s += D[6*r + k] * B[k][c];
            DB[r][c] = s;
        }
        double w = wt * vol;
        for (i = 0; i < nd; i++) for (j = 0; j < nd; j++) {
            double s = 0.0;
            for (k = 0; k < 6; k++) s += B[k][i] * DB[k][j];
            Ke[i*nd + j] += w * s;
        }
    }
    return 1;
}

/* Assemble K straight into a CSR matrix whose pattern is given at node level:
     nptr[nn+1], nidx[nnz_nodes] (sorted per row); the dof-level CSR is the 3x3-block expansion:
     row 3*i+a starts at 9*nptr[i] + a*3*k_i  (k_i = nptr[i+1]-nptr[i]) and holds 3 entries per node column.
   scale[ne] (may be NULL) multiplies each element matrix (secant / damage / nonlinear updates).
   data (length 9*nnz_nodes) must be zeroed by the caller.   Returns the number of degenerate elements.        */
int64_t cfea_assemble(int order, int64_t ne, const double *nodes, const int32_t *conn, const double *D, const double *scale,
                   const int32_t *nptr, const int32_t *nidx, double *data) {
    int n = order == 2 ? 10 : 4;
    int64_t bad = 0, e;
#pragma omp parallel for schedule(static) reduction(+:bad)
    for (e = 0; e < ne; e++) {
        double x[12], Ke[900], vol;
        int i, j, a, b;
        const int32_t *cn = conn + e * n;
        double s = scale ? scale[e] : 1.0;
        if (s == 0.0) continue;
        for (i = 0; i < 4; i++) { x[3*i] = nodes[3*cn[i]]; x[3*i+1] = nodes[3*cn[i]+1]; x[3*i+2] = nodes[3*cn[i]+2]; }
        if (!element_ke(order, x, D, Ke, &vol)) { bad++; continue; }
        for (i = 0; i < n; i++) {
            int ri = cn[i];
            int lo0 = nptr[ri], k_i = nptr[ri + 1] - lo0;
            int64_t rs = 9 * (int64_t)lo0;
            for (j = 0; j < n; j++) {
                int cj = cn[j], lo = lo0, hi = nptr[ri + 1] - 1, p = -1;
                while (lo <= hi) {                       /* binary search of the node column in the row */
                    int mid = (lo + hi) >> 1;
                    if (nidx[mid] < cj) lo = mid + 1; else if (nidx[mid] > cj) hi = mid - 1; else { p = mid - lo0; break; }
                }
                if (p < 0) continue;
                for (a = 0; a < 3; a++) for (b = 0; b < 3; b++) {
                    double v = s * Ke[(3*i + a) * (3*n) + 3*j + b];
#pragma omp atomic
                    data[rs + (int64_t)a * 3 * k_i + 3 * (int64_t)p + b] += v;
                }
            }
        }
    }
    return bad;
}

/* strain at the element centre for each element: eps[ne][6] from the displacement vector u (3 per node) */
void cfea_centre_strain(int order, int64_t ne, const double *nodes, const int32_t *conn, const double *u, double *eps) {
    int n = order == 2 ? 10 : 4;
    int64_t e;
#pragma omp parallel for schedule(static)
    for (e = 0; e < ne; e++) {
        double x[12], gL[4][3], vol, dN[MAXN][4], L[4] = {0.25, 0.25, 0.25, 0.25};
        const int32_t *cn = conn + e * n;
        double s[6] = {0, 0, 0, 0, 0, 0};
        int i, k;
        for (i = 0; i < 4; i++) { x[3*i] = nodes[3*cn[i]]; x[3*i+1] = nodes[3*cn[i]+1]; x[3*i+2] = nodes[3*cn[i]+2]; }
        if (!grad_L(x, gL, &vol)) { for (k = 0; k < 6; k++) eps[6*e + k] = 0.0; continue; }
        dnd(order, L, dN);
        for (i = 0; i < n; i++) {
            double g[3], ux = u[3*cn[i]], uy = u[3*cn[i]+1], uz = u[3*cn[i]+2];
            for (k = 0; k < 3; k++) g[k] = dN[i][0]*gL[0][k] + dN[i][1]*gL[1][k] + dN[i][2]*gL[2][k] + dN[i][3]*gL[3][k];
            s[0] += g[0]*ux; s[1] += g[1]*uy; s[2] += g[2]*uz;
            s[3] += g[1]*ux + g[0]*uy;
            s[4] += g[2]*uy + g[1]*uz;
            s[5] += g[2]*ux + g[0]*uz;
        }
        for (k = 0; k < 6; k++) eps[6*e + k] = s[k];
    }
}
