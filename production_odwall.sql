/*
Navicat SQLite Data Transfer

Source Server         : NOV
Source Server Version : 30706
Source Host           : :0

Target Server Type    : SQLite
Target Server Version : 30706
File Encoding         : 65001

Date: 2025-07-07 17:17:00
*/

PRAGMA foreign_keys = OFF;

-- ----------------------------
-- Table structure for "main"."production_odwall"
-- ----------------------------
DROP TABLE "main"."production_odwall";
CREATE TABLE "production_odwall" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "od" decimal NULL, "wall" decimal NULL, "size" varchar(50) NULL, "process_type_id" bigint NULL REFERENCES "production_process" ("id") DEFERRABLE INITIALLY DEFERRED);

-- ----------------------------
-- Records of production_odwall
-- ----------------------------
INSERT INTO "main"."production_odwall" VALUES (5, 18.625, 0.435, '18.625'''' X 0.435''''', 1);
INSERT INTO "main"."production_odwall" VALUES (6, 18.625, 0.5, '18.625'''' X 0.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (7, 18.625, 0.625, '18.625'''' X 0.625''''', 1);
INSERT INTO "main"."production_odwall" VALUES (8, 20, 0.625, '20'''' X 0.625''''', 1);
INSERT INTO "main"."production_odwall" VALUES (9, 20, 0.635, '20'''' X 0.635''''', 1);
INSERT INTO "main"."production_odwall" VALUES (10, 20, 0.75, '20'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (11, 20, 0.812, '20'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (12, 20, 1, '20'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (13, 21, 1.25, '21'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (14, 22, 0.5, '22'''' X 0.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (15, 22, 0.625, '22'''' X 0.625''''', 1);
INSERT INTO "main"."production_odwall" VALUES (16, 22, 0.75, '22'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (17, 22, 0.812, '22'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (18, 22, 1, '22'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (19, 22, 1.25, '22'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (20, 22, 1.5, '22'''' X 1.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (21, 24, 0.5, '24'''' X 0.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (22, 24, 0.5, '24'''' X 0.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (23, 24, 0.625, '24'''' X 0.625''''', 1);
INSERT INTO "main"."production_odwall" VALUES (24, 24, 0.75, '24'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (25, 24, 0.812, '24'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (26, 24, 1, '24'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (27, 24, 1.25, '24'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (28, 24, 1.5, '24'''' X 1.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (29, 26, 0.625, '26'''' X 0.625''''', 1);
INSERT INTO "main"."production_odwall" VALUES (30, 26, 0.75, '26'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (31, 26, 0.812, '26'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (32, 26, 1, '26'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (33, 26, 1.25, '26'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (34, 26, 1.5, '26'''' X 1.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (35, 28, 0.75, '28'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (36, 30, 0.625, '30'''' X 0.625''''', 1);
INSERT INTO "main"."production_odwall" VALUES (37, 30, 0.75, '30'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (38, 30, 0.812, '30'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (39, 30, 1, '30'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (40, 30, 1.25, '30'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (41, 30, 1.5, '30'''' X 1.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (42, 30, 1.75, '30'''' X 1.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (43, 30, 2, '30'''' X 2.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (44, 32, 0.75, '32'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (45, 32, 0.812, '32'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (46, 32, 1, '32'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (47, 32, 1.25, '32'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (48, 32, 1.5, '32'''' X 1.50''''', 1);
INSERT INTO "main"."production_odwall" VALUES (49, 32, 2, '32'''' X 2.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (50, 36, 0.75, '36'''' X 0.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (51, 36, 0.812, '36'''' X 0.812''''', 1);
INSERT INTO "main"."production_odwall" VALUES (52, 36, 1, '36'''' X 1.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (53, 36, 1.25, '36'''' X 1.250''''', 1);
INSERT INTO "main"."production_odwall" VALUES (54, 36, 1.5, '36'''' X 1.500''''', 1);
INSERT INTO "main"."production_odwall" VALUES (55, 36, 1.75, '36'''' X 1.750''''', 1);
INSERT INTO "main"."production_odwall" VALUES (56, 36, 2, '36'''' X 2.000''''', 1);
INSERT INTO "main"."production_odwall" VALUES (57, 20, 0.5, '20'''' X 0.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (58, 20, 0.625, '20'''' X 0.625''''', 2);
INSERT INTO "main"."production_odwall" VALUES (59, 20, 0.75, '20'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (60, 20, 0.812, '20'''' X 0.812''''', 2);
INSERT INTO "main"."production_odwall" VALUES (61, 20, 1, '20'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (62, 20, 1.25, '20'''' X 1.250''''', 2);
INSERT INTO "main"."production_odwall" VALUES (63, 22, 0.5, '22'''' X 0.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (64, 22, 0.625, '22'''' X 0.625''''', 2);
INSERT INTO "main"."production_odwall" VALUES (65, 22, 0.75, '22'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (66, 22, 1, '22'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (67, 22, 1.25, '22'''' X 1.250''''', 2);
INSERT INTO "main"."production_odwall" VALUES (68, 24, 0.5, '24'''' X 0.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (69, 24, 0.625, '24'''' X 0.625''''', 2);
INSERT INTO "main"."production_odwall" VALUES (70, 24, 0.635, '24'''' X 0.635''''', 2);
INSERT INTO "main"."production_odwall" VALUES (71, 24, 0.75, '24'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (72, 24, 0.812, '24'''' X 0.812''''', 2);
INSERT INTO "main"."production_odwall" VALUES (73, 24, 1, '24'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (74, 24, 1.25, '24'''' X 1.250''''', 2);
INSERT INTO "main"."production_odwall" VALUES (75, 24, 1.5, '24'''' X 1.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (76, 26, 0.625, '26'''' X 0.625''''', 2);
INSERT INTO "main"."production_odwall" VALUES (77, 26, 0.75, '26'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (78, 26, 0.812, '26'''' X 0.812''''', 2);
INSERT INTO "main"."production_odwall" VALUES (79, 26, 1, '26'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (80, 26, 1.25, '26 '''' X 1.250''''', 2);
INSERT INTO "main"."production_odwall" VALUES (81, 26, 1.5, '26'''' X 1.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (82, 28, 0.625, '28'''' X 0.625''''', 2);
INSERT INTO "main"."production_odwall" VALUES (83, 28, 0.75, '28'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (84, 28, 1, '28'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (85, 30, 0.625, '30'''' X 0.625''''', 2);
INSERT INTO "main"."production_odwall" VALUES (86, 30, 0.75, '30'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (87, 30, 0.875, '30'''' X 0.875''''', 2);
INSERT INTO "main"."production_odwall" VALUES (88, 30, 1, '30'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (89, 30, 1.25, '30'''' X 1.250''''', 2);
INSERT INTO "main"."production_odwall" VALUES (90, 30, 1.5, '30'''' X 1.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (91, 30, 2, '30'''' X 2.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (92, 30, 1.125, '30'''' X 1.125''''', 2);
INSERT INTO "main"."production_odwall" VALUES (93, 32, 0.5, '32'''' X 0.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (94, 32, 0.75, '32'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (95, 32, 1, '32'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (96, 36, 0.5, '36'''' X 0.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (97, 36, 0.75, '36'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (98, 36, 0.875, '26'''' X 0.875''''', 2);
INSERT INTO "main"."production_odwall" VALUES (99, 36, 1, '36'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (100, 36, 1.25, '36'''' X 1.250''''', 2);
INSERT INTO "main"."production_odwall" VALUES (101, 36, 1.5, '36'''' X 1.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (102, 36, 2, '36'''' X 2.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (103, 36, 2.5, '36'''' X 2.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (104, 40, 0.75, '40'''' X 0.750', 2);
INSERT INTO "main"."production_odwall" VALUES (105, 42, 1, '42'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (106, 42, 1.5, '42'''' X 1.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (107, 42, 2, '42'''' X 2.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (108, 42, 2.5, '42'''' X 2.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (109, 46, 1, '46'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (110, 48, 0.75, '48'''' X 0.750''''', 2);
INSERT INTO "main"."production_odwall" VALUES (111, 48, 1, '48'''' X 1.000''''', 2);
INSERT INTO "main"."production_odwall" VALUES (112, 48, 1.5, '48'''' X 1.500''''', 2);
INSERT INTO "main"."production_odwall" VALUES (113, 48, 2, '48'''' X 2.000''''', 2);

-- ----------------------------
-- Indexes structure for table production_odwall
-- ----------------------------
CREATE INDEX "main"."production_odwall_process_type_id_2d74a754"
ON "production_odwall" ("process_type_id" ASC);
