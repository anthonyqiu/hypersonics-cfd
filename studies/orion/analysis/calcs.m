% FREESTREAM PROPERTIES
rho = 1.2;
mu = 1.8e-5;
nu = mu / rho;
M = 1.5;
gamma = 1.4;
R = 287;
T = 293;
U_inf = M * sqrt(gamma * R * T);

% ORION SHAPE
D = 5;

% FIRST LAYER GRID SPACING CALC
Re_L = rho * U_inf * D  / mu;
C_f = 0.0592 * Re_L ^ (-1 / 5);
tau_w = (1 / 2) * rho * U_inf ^ 2 * C_f;
u_tau = sqrt(tau_w / rho);
y1_plus = 1;
y1 = y1_plus * nu / u_tau;

firstCellSpacing = y1 * 2;